# books/services.py

# import math
import numpy as np
from numpy.linalg import norm
from django.utils import timezone
from datetime import timedelta

from .models import Book
from django.db.models import Q
from daybydaybackend.diary.models import Diary, DailyRecommended, UserFeedback
from django.contrib.contenttypes.models import ContentType

def recommend_books(user_emotion:dict, mode: str = 'maintain', count: int = 3, user=None):
    # 최근 5회의 추천 세션에서 책들의 카테고리 수집하여 벌점 대상 지정
    penalty_categories = set()
    if user and user.is_authenticated:
        recent_recs = DailyRecommended.objects.filter(
            diary__user=user
        ).prefetch_related('books').order_by('-diary__created_at')[:5]  
        for rec in recent_recs:
            for b in rec.books.all():
                if getattr(b, 'category', None):
                    penalty_categories.add(b.category)

    # 계산을 위해 리스트 형태로 변경
    ordered_keys = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']

    u_vec = np.array([user_emotion.get(key, 0.0) for key in ordered_keys])
    
    # 타겟 벡터 설정
    target_vec = _get_target_emotion(u_vec, mode)

    # 태그 0,0,0,0,0,0,0,0 인 책은 추천에서 제외 (리뷰 부족)
    all_books = Book.objects.filter(
        Q(joy__gt=0.0) | Q(sadness__gt=0.0) | Q(anger__gt=0.0) | Q(fear__gt=0.0) | Q(trust__gt=0.0) | Q(surprise__gt=0.0),
        link__isnull=False
    )

    t_norm = norm(target_vec)
    if t_norm == 0:
        t_norm = 1e-9

    filtered_and_scored = []
    fallback_list = []

    # 감정 범위 임계값
    if mode == 'maintain':
        radius_limit = 0.6
    elif mode == 'shift':
        radius_limit = 1.2
    elif mode == 'amplification':
        radius_limit = 0.8
    else:
        radius_limit = 0.7

    # 코사인 유사도&유클리드 거리 결합 가중치 (1에 가까울 수록 유클리드 거리 중시)
    if mode == 'maintain':
        alpha = 0.90
    elif mode == 'amplification':
        alpha = 0.80
    else:
        alpha = 0.30

    for book in all_books:
        b_vec = np.array([
            book.joy, book.sadness, book.anger, 
            book.fear, book.trust, book.surprise
        ])

        pure_distance = np.sqrt(np.sum((target_vec - b_vec) ** 2))
        norm_euclidean = _calculate_euclidean(target_vec, b_vec)
        cosine_dist = _calculate_cosine(target_vec, b_vec, t_norm)

        final_score = (alpha * norm_euclidean) + ((1.0 - alpha) * cosine_dist)
        
        # [다양성 패치] 과거에 추천받았던 카테고리가 겹치면 패널티 가중치를 주어 순위를 뒤로 밀어냄
        if getattr(book, 'category', None) in penalty_categories:
            final_score += 0.05
        
        # 임계값 내에 있는 콘텐츠만 filtered_and_scored에 추가 
        if pure_distance <= radius_limit:
            filtered_and_scored.append((final_score, book, pure_distance)) 

        fallback_list.append((final_score, book, pure_distance))

    # [1단계] 객관적인 감정 치료 우선으로 안전 후보군(Top 10) 선별
    pool_size = max(count * 3, 10)
    
    if len(filtered_and_scored) >= count:
        filtered_and_scored.sort(key=lambda x: x[0])
        safe_pool = filtered_and_scored[:pool_size]
        is_fallback = False
    else:
        # 추천 콘텐츠 수 < count 일 때 fallback 리스트에서 순수 거리순 추출
        fallback_list.sort(key=lambda x: x[2])
        safe_pool = fallback_list[:pool_size]
        is_fallback = True

    # =========================================================================
    # [안전장치 및 2단계] 치료 임계치 검증 & 안전 후보군 내 취향 재정렬
    # =========================================================================
    if user and user.is_authenticated and len(safe_pool) > 0:
        liked_categories = set()
        recently_disliked_categories = set()
        
        # 1. 유저의 선호 장르(좋아요) 및 기피 장르(최근 3일 싫어요) 카테고리 수집
        book_type = ContentType.objects.get_for_model(Book)
        
        liked_isbns = UserFeedback.objects.filter(
            user=user, feedback_type='LIKE', content_type=book_type
        ).values_list('object_id', flat=True)
        if liked_isbns:
            liked_categories = set(Book.objects.filter(isbn__in=liked_isbns).values_list('category', flat=True))
            
        three_days_ago = timezone.now() - timedelta(days=3)
        disliked_isbns = UserFeedback.objects.filter(
            user=user, feedback_type='DISLIKE', content_type=book_type,
            created_at__gte=three_days_ago
        ).values_list('object_id', flat=True)
        if disliked_isbns:
            recently_disliked_categories = set(Book.objects.filter(isbn__in=disliked_isbns).values_list('category', flat=True))

        # 2. [치료 임계치 검증] 유저 선호 장르 중 '진짜 치유력'이 있는 작품이 존재하는가?
        # - 치료 마지노선 임계값은 radius_limit의 50% 지점 (예: shift 모드는 0.6)
        therapeutic_threshold = radius_limit * 0.5
        has_effective_preferred_book = False
        
        for item in safe_pool:
            book = item[1]
            pure_distance = item[2]
            category = getattr(book, 'category', None)
            if category and category in liked_categories:
                if pure_distance <= therapeutic_threshold:
                    has_effective_preferred_book = True
                    break

        # 3. 순위 재정렬 수행
        # - 선호 장르가 있고 최소 치료 임계값을 통과한 경우에만 우선순위 상승 적용 (Bypass 방지)
        # - 기피 장르는 언제나 순위를 뒤로 밀어냄 (3일 임시 패널티)
        def get_preference_rank(item):
            score, book, pure_dist = item
            category = getattr(book, 'category', None)
        
            pref_score = 0
            if category in liked_categories:
                pref_score = -0.1 
            elif category in recently_disliked_categories:
                pref_score = 0.1 # 패널티는 거리를 늘려 우선순위 하락
                
            return score + pref_score

        # Python의 stable sort 특성을 이용하여 감정 거리 순위를 최대한 보존하면서 취향 반영
        safe_pool.sort(key=get_preference_rank)

    # 최종 노출할 개수(count) 만큼만 반환
    return [item[1] for item in safe_pool[:count]], is_fallback


def get_or_create_book_recommendation(diary_obj, user_emotion: dict, mode: str, count: int, user=None):
    daily_rec, created = DailyRecommended.objects.get_or_create(diary=diary_obj, mode=mode)
    saved_count = daily_rec.books.count()

    if created or saved_count == 0 or saved_count < count:
        recommended_books, is_fallback = recommend_books(user_emotion=user_emotion, mode=mode, count=count, user=user)

        daily_rec.books.set(recommended_books)
        daily_rec.is_book_fallback = is_fallback
        daily_rec.save(update_fields=['is_book_fallback'])
    
    else:
        recommended_books = daily_rec.books.all()[:count]
        is_fallback = daily_rec.is_book_fallback
        
    return recommended_books, is_fallback


def get_saved_book_metadata(diary_obj):
    return DailyRecommended.objects.filter(diary=diary_obj).prefetch_related('books')

def _calculate_euclidean(t_vec: np.ndarray, b_vec: np.ndarray) -> float:
    # 가중 유클리드 거리 계산 및 정규화 (0~1 사이)
    ecuclidean_dist = np.sqrt(np.sum((t_vec - b_vec) ** 2))
    max_euclidean = np.sqrt(6.0)

    return ecuclidean_dist / max_euclidean

def _calculate_cosine(t_vec: np.ndarray, b_vec: np.ndarray, t_norm: float) -> float:
    # 코사인 유사도 계산
    b_norm = norm(b_vec)

    if b_norm == 0:
        b_norm = 1e-9

    cosine_sim = np.dot(t_vec, b_vec) / (t_norm * b_norm)
    return 1.0 - cosine_sim

def _get_target_emotion(u_vec: np.ndarray, mode: str) -> np.ndarray:
    # 추천 모드에 따라 추천의 기준이 될 목표 감정 벡터를 생성
    target_vec = u_vec.copy()
    
    if mode == 'shift':
        target_vec[1:4] *= 0.2  # sadness, anger, fear
        target_vec[0] += 0.3    # joy
        target_vec[4] += 0.2    # trust
        
    elif mode == 'amplification':
        target_vec[0] *= 1.5    # joy
        target_vec[4] *= 1.5    # trust

    target_vec = np.maximum(target_vec, 0)

    if np.sum(target_vec) > 0:
        target_vec = target_vec / np.sum(target_vec)
    else:
        target_vec = np.ones_like(target_vec) / len(target_vec)

    # maintain 모드일 경우 그대로
    return target_vec

def get_user_weighted_emotion(user, target_datetime=None):
    # 최근 일주일 간 감정 벡터를 가중치를 적용해 하나의 감정 벡터로 리턴  
    target_date = target_datetime.date()
    seven_days_ago = target_datetime - timedelta(days=7)

    # 7일 이내 데이터만 필터링
    queryset = Diary.objects.filter(
        user=user,
        created_at__lte=target_datetime,
        created_at__gte=seven_days_ago
    ).select_related('emotion')

    diaries = queryset.order_by('-created_at')
    
    # 감정 데이터가 유효한 일기만 필터링
    valid_diaries = [d for d in diaries if hasattr(d, 'emotion') and d.emotion is not None]
    if not valid_diaries:
        return None
    
    # 상수에서 유저 variance 반영한 가중치로 변경
    user_profile = getattr(user, 'userprofile', None)
    variance = getattr(user_profile, 'emotion_variance', 0.05) if user_profile else 0.05

    decay_rate = 0.5 + (variance * 1.5)
    decay_rate = min(max(decay_rate, 0.4), 0.85)

    fields = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']
    weighted_sum = {field: 0.0 for field in fields}
    total_weight = 0.0

    for d in valid_diaries:
        days_diff = (target_date - d.created_at.date()).days
        
        # 작성 당일 ~ 6일 전 데이터만 가중치 적용
        if 0 <= days_diff < 7:
            weight = (1.0 - decay_rate) ** days_diff
            total_weight += weight
            
            for field in fields:
                emotion_value = getattr(d.emotion, field, 0.0) or 0.0
                weighted_sum[field] += emotion_value * weight

    # 유효한 가중치가 없는 경우 
    if total_weight == 0:
        return None

    weighted_emotion = {}
    raw_values = []
    for field in fields:
        val = round(weighted_sum[field] / total_weight, 4)
        weighted_emotion[field] = val
        raw_values.append(val)

    total_sum = sum(raw_values)
    if total_sum > 0:
        for field in fields:
            weighted_emotion[field] = round(weighted_emotion[field] / total_sum, 4)
        
    return weighted_emotion