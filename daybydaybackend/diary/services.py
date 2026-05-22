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
    외부 Kiwi 형태소 분석 마이크로서비스를 호출하여 완성된 감정 분석 결과를 그대로 리턴합니다.
    """
    return get_analyzer().analyze(text)



def analyze_emotion_with_gemini(text: str) -> dict:
    """
    하위 호환용 함수. 기존 호출부를 위해 유지하며 내부적으로 하이브리드 분석을 사용한다.
    """
    return analyze_emotion_hybrid(text)
