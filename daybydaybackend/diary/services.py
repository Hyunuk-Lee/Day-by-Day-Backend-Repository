from .models import Diary, DiaryEmotion
from .emotion_analyzer import EmotionAnalyzer


# ===== 일기 작성 비즈니스 로직 =====
def create_diary_entry(user, content, weather=None, image=None):
    """
    새로운 일기를 작성하여 저장하는 로직
    """
    diary = Diary.objects.create(user=user, content=content, weather=weather, image=image)
    return diary



# ===== 감정 분석 비즈니스 로직 =====
def process_diary_emotion(diary_id, user):
    """
    일기 ID를 기반으로 AI 분석을 수행하고 DB에 결과를 반영하는 비즈니스 로직
    """
    # 1. 유저 권한 및 일기 존재 여부 확인
    diary = Diary.objects.get(id=diary_id, user=user)
    
    # 2. Kiwi + 감정사전 + 선택적 Gemini fallback 분석
    emotion_dict = analyze_emotion_hybrid(diary.content)
    
    # 3. 데이터 갱신 또는 생성
    DiaryEmotion.objects.update_or_create(
        diary=diary,
        defaults={
            'joy': emotion_dict.get('joy', 0.0),
            'sadness': emotion_dict.get('sadness', 0.0),
            'anger': emotion_dict.get('anger', 0.0),
            'fear': emotion_dict.get('fear', 0.0),
            'trust': emotion_dict.get('trust', 0.0),
            'surprise': emotion_dict.get('surprise', 0.0),
            'valence': emotion_dict.get('valence', 0.0),
            'arousal': emotion_dict.get('arousal', 0.0),
            'primary_emotion': emotion_dict.get('primary_emotion', '알수없음')
        }
    )
    return diary

_analyzer = None

def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = EmotionAnalyzer()
    return _analyzer

def analyze_emotion_hybrid(text: str) -> dict:
    """
    Kiwi 형태소 분석 + NRC/KNU 사전 + 선택적 Gemini fallback 기반 감정 분석
    """
    emotion_6d = get_analyzer().analyze(text)
    valence = _compute_valence(emotion_6d)
    arousal = _compute_arousal(emotion_6d)
    primary_emotion = _primary_emotion(emotion_6d)

    return {
        **emotion_6d,
        'valence': valence,
        'arousal': arousal,
        'primary_emotion': primary_emotion,
    }


def _compute_valence(emotions: dict) -> float:
    positive = (emotions.get('joy', 0.0) + emotions.get('trust', 0.0)) / 2.0
    negative = (
        emotions.get('sadness', 0.0)
        + emotions.get('anger', 0.0)
        + emotions.get('fear', 0.0)
    ) / 3.0
    value = positive - negative
    return round(max(-1.0, min(1.0, value)), 4)


def _compute_arousal(emotions: dict) -> float:
    active = (emotions.get('anger', 0.0) + emotions.get('surprise', 0.0)) / 2.0
    calm = (emotions.get('sadness', 0.0) + emotions.get('trust', 0.0)) / 2.0
    value = active - calm
    return round(max(-1.0, min(1.0, value)), 4)


def _primary_emotion(emotions: dict) -> str:
    if not emotions:
        return '알수없음'

    label_map = {
        'joy': '기쁨',
        'sadness': '슬픔',
        'anger': '분노',
        'fear': '두려움',
        'trust': '신뢰',
        'surprise': '놀람',
    }
    key = max(label_map.keys(), key=lambda k: emotions.get(k, 0.0))
    if emotions.get(key, 0.0) <= 0:
        return '알수없음'
    return label_map[key]


def get_user_recent_average_emotion(user):
    """
    유저의 최근 5개 일기의 감정 데이터를 평균내어 반환합니다.
    일기 데이터가 없거나 감정 분석 결과가 없으면 None을 반환합니다.
    """
    diaries = Diary.objects.filter(user=user).select_related('emotion')[:5]
    emotions = [d.emotion for d in diaries if hasattr(d, 'emotion') and d.emotion is not None]
    if not emotions:
        return None, diaries
    
    count = len(emotions)
    avg_emotion = {
        'joy': round(sum(e.joy for e in emotions) / count, 4),
        'sadness': round(sum(e.sadness for e in emotions) / count, 4),
        'anger': round(sum(e.anger for e in emotions) / count, 4),
        'fear': round(sum(e.fear for e in emotions) / count, 4),
        'trust': round(sum(e.trust for e in emotions) / count, 4),
        'surprise': round(sum(e.surprise for e in emotions) / count, 4),
        'valence': round(sum(e.valence for e in emotions) / count, 4),
        'arousal': round(sum(e.arousal for e in emotions) / count, 4),
    }
    return avg_emotion, diaries


def determine_auto_recommendation_mode(user, current_diary) -> str:
    """
    유저의 최근 5개 일기(현재 일기 포함)의 감정 데이터를 조회하고,
    통계적 분산(Variance)과 평균을 계산하여 추천 모드를 자동으로 결정합니다.
    """
    from .models import DiaryEmotion, Diary
    
    # 1. 최근 4개의 과거 일기를 '날짜 내림차순(최신순)'으로 가져옴
    past_diaries = list(Diary.objects.filter(
        user=user
    ).exclude(
        id=current_diary.id
    ).order_by('-created_at')[:4])
    
    # DB에서 가져온 과거 일기들을 오름차순(과거->최신)으로 뒤집고 현재 일기를 맨 뒤에 붙임
    diaries = past_diaries[::-1] + [current_diary]
    
    emotions = []
    current_diary_has_emotion = False
    
    for d in diaries:
        try:
            if hasattr(d, 'emotion') and d.emotion is not None:
                emotions.append(d.emotion)
                if d.id == current_diary.id:
                    current_diary_has_emotion = True
        except DiaryEmotion.DoesNotExist:
            continue
            
    if not emotions:
        return 'maintain'
        
    count = len(emotions)
    
    # 오늘 일기(current_diary)에 감정이 정상적으로 등록되어 있는 경우에만 긍정 정서 가드를 적용
    if current_diary_has_emotion:
        current_emotion = emotions[-1]  # 오늘의 감정 (가장 최신)
        is_today_positive = current_emotion.primary_emotion in ['기쁨', '신뢰']
    else:
        is_today_positive = False

    # 2. 통계치 계산을 위한 부정 감정 리스트 수집
    neg_keys = ['sadness', 'anger', 'fear']
    neg_data = {key: [getattr(e, key, 0.0) or 0.0 for e in emotions] for key in neg_keys}
    
    def calc_mean_and_variance(data_list):
        n = len(data_list)
        if n == 0:
            return 0.0, 0.0
        mean_val = sum(data_list) / n
        if n <= 1:
            return mean_val, 0.0
        variance_val = sum((x - mean_val) ** 2 for x in data_list) / (n - 1)
        return mean_val, variance_val

    # 오늘 기분이 좋은 상태가 아닐 때만 '부정 정서 고착(Shift)'을 검사함
    if not is_today_positive:
        # 3. 장기적 정서 고착(Stagnation) 여부 판정
        # 규칙 A: 특정 부정 감정의 평균 >= 0.35 이고 분산 < 0.025
        stagnant_by_stats = False
        for key in neg_keys:
            mean_v, var_v = calc_mean_and_variance(neg_data[key])
            if count >= 2 and mean_v >= 0.33 and var_v < 0.015:
                stagnant_by_stats = True
                break
                
        # 규칙 B: 연속 3일 이상 특정 부정 감정이 대표 감정으로 나타남
        stagnant_by_continuity = False
        if count >= 3:
            neg_korean_labels = {'sadness': '슬픔', 'anger': '분노', 'fear': '두려움'}
            primary_emotions = [e.primary_emotion for e in emotions]
            
            for label in neg_korean_labels.values():
                consecutive = 0
                for pe in primary_emotions:
                    if pe == label:
                        consecutive += 1
                        if consecutive >= 3:
                            stagnant_by_continuity = True
                            break
                    else:
                        consecutive = 0
                if stagnant_by_continuity:
                    break
                    
        if stagnant_by_stats or stagnant_by_continuity:
            return 'shift'
            
        # 4. 일시적 정서적 일탈(Volatility) 판정
        volatile_by_stats = False
        for key in neg_keys:
            mean_v, var_v = calc_mean_and_variance(neg_data[key])
            if count >= 2 and mean_v >= 0.33 and var_v >= 0.015:
                volatile_by_stats = True
                break
                
        if volatile_by_stats:
            return 'maintain'

    # 5. 긍정 정서의 지속 및 극대화(Amplification) 판정
    else:
        joy_trust_sum = [ (e.joy or 0.0) + (e.trust or 0.0) for e in emotions]
        jt_mean, _ = calc_mean_and_variance(joy_trust_sum)
        
        # 전체 감정의 50% 이상이 긍정일 때
        if jt_mean >= 0.5:
            return 'amplification'
            
    # 6. 기본 상태
    return 'maintain'

def update_user_emotion_volatility(user, current_diary):
    """
    오늘 일기와 어제 일기의 감정 차이를 계산하여 
    유저 프로필의 정서 분산도를 지수이동평균(EMA)으로 업데이트
    """
    from datetime import timedelta
    from .models import Diary 
    
    user_profile = getattr(user, 'userprofile', None)
    if not user_profile:
        return  

    # 직전 작성 일기 조회
    yesterday_date = current_diary.created_at - timedelta(days=1)
    yesterday_diary = Diary.objects.filter(
        user=user, 
        created_at=yesterday_date
    ).select_related('emotion').first()
    
    if not yesterday_diary or not hasattr(yesterday_diary, 'emotion') or yesterday_diary.emotion is None:
        return
        
    current_emotion = getattr(current_diary, 'emotion', None)
    if not current_emotion:
        return

    fields = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']
    diff_squared_sum = 0.0
    for field in fields:
        curr_val = getattr(current_emotion, field, 0.0) or 0.0
        yest_val = getattr(yesterday_diary.emotion, field, 0.0) or 0.0
        diff_squared_sum += (curr_val - yest_val) ** 2

    today_volatility = diff_squared_sum / len(fields)
    
    # EMA 적용
    alpha = 0.2
    old_volatility = user_profile.emotion_volatility
    
    user_profile.emotion_volatility = (1.0 - alpha) * old_volatility + alpha * today_volatility
    user_profile.save()