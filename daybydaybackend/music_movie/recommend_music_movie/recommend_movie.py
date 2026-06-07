import os
import json
import math
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, 'emotion_tags.json')

with open(JSON_PATH, 'r', encoding='utf-8') as f:
    TAG_EMOTION_MAP = json.load(f)

def build_6d_emotion_vector(tags):
    ordered_keys = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']
    total_vector = {key: 0.0 for key in ordered_keys}
    matched_count = 0
    for tag in tags:
        tag = str(tag).lower().strip()
        if tag in TAG_EMOTION_MAP:
            matched_count += 1
            tag_vec = TAG_EMOTION_MAP[tag]
            for key in ordered_keys:
                total_vector[key] += tag_vec.get(key, 0.0)
    if matched_count == 0:
        return [0.0] * 6
    return [round(total_vector[key] / matched_count, 4) for key in ordered_keys]

def _get_target_emotion_vector(u_vec: np.ndarray, mode: str) -> np.ndarray:
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

def _get_direction_weights(u_vec, mode):
    weights = [1.0] * 6
    if mode == 'maintain': 
        return weights
    elif mode == 'shift':
        target = _get_target_emotion_vector(u_vec, mode)
        weights = [2.0 if t > 0.5 else 1.0 for t in target]
    elif mode == 'amplification':
        weights = [0.5] * 6
        weights[0] = 3.0  # joy
        weights[4] = 3.0  # trust
    return weights

def _calculate_euclidean(u_vec, b_vec, w_vec):
    euclidean_dist = math.sqrt(sum(w * ((u - b) ** 2) for u, b, w in zip(u_vec, b_vec, w_vec)))
    max_euclidean = math.sqrt(sum(w_vec)) 
    if max_euclidean == 0: return 0.0
    return euclidean_dist / max_euclidean

def _calculate_cosine(u_vec, b_vec, u_norm):
    b_norm = math.sqrt(sum(b ** 2 for b in b_vec)) or 1e-9
    dot_product = sum(u * b for u, b in zip(u_vec, b_vec))
    return 1.0 - (dot_product / (u_norm * b_norm))

class MovieEmotionRecommender:
    def recommend_movies(self, user_emotion, movie_data, mode='maintain', top_n=3, user=None):
        recent_genres = set()
        
        liked_movie_genres = set()
        disliked_movie_genres = set()
        disliked_ids = []

        if user and user.is_authenticated:
            from daybydaybackend.diary.models import DailyRecommended, UserFeedback
            from daybydaybackend.music_movie.models import Movie
            from django.contrib.contenttypes.models import ContentType
            from django.utils import timezone
            from datetime import timedelta
            
            recent_recs = DailyRecommended.objects.filter(
            diary__user=user
            ).prefetch_related('movies').order_by('-diary__created_at')[:5]  
            for rec in recent_recs:
                for mv in rec.movies.all():
                    if getattr(mv, 'genre', None):
                        recent_genres.add(mv.genre)

            movie_type = ContentType.objects.get_for_model(Movie)

            # 좋아요 영화 장르 수집
            liked_ids = UserFeedback.objects.filter(
                user=user, feedback_type='LIKE', content_type=movie_type
            ).values_list('object_id', flat=True)
            if liked_ids:
                for m in Movie.objects.filter(tmdb_id__in=liked_ids):
                    if getattr(m, 'genre', None):
                        for g in m.genre.split(','):
                            liked_movie_genres.add(g.strip().lower())

            # 싫어요 누른 특정 영화 ID 및 최근 3일 기피 장르 수집
            disliked_ids = list(UserFeedback.objects.filter(
                user=user, feedback_type='DISLIKE', content_type=movie_type
            ).values_list('object_id', flat=True))

            three_days_ago = timezone.now() - timedelta(days=3)
            recent_disliked_ids = UserFeedback.objects.filter(
                user=user, feedback_type='DISLIKE', content_type=movie_type,
                created_at__gte=three_days_ago
            ).values_list('object_id', flat=True)
            if recent_disliked_ids:
                for m in Movie.objects.filter(tmdb_id__in=recent_disliked_ids):
                    if getattr(m, 'genre', None):
                        for g in m.genre.split(','):
                            disliked_movie_genres.add(g.strip().lower())

        ordered_keys = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']
        u_vec = [float(user_emotion.get(key, 0.0)) for key in ordered_keys]
        
        target_vec = _get_target_emotion_vector(u_vec, mode)
        target_norm = math.sqrt(sum(t ** 2 for t in target_vec)) or 1e-9
        w_vec = _get_direction_weights(u_vec, mode)
        
        radius_limit = 0.6 if mode == 'maintain' else (1.2 if mode == 'shift' else 0.8)
        if mode == 'maintain': 
            alpha = 0.90
        elif mode == 'amplification': 
            alpha = 0.80
        else: 
            alpha = 0.30

        filtered_and_scored = []
        fallback_list = []

        # [1단계] 순수 감정 후보군 추출
        for movie in movie_data:
            movie_id = str(movie.get('movie_id') or movie.get('tmdb_id'))      
            b_vec = [float(movie.get(k, 0.0) or 0.0) for k in ordered_keys]
            
            sum_b = sum(b_vec)
            if sum_b > 0:
                b_vec = [x / sum_b for x in b_vec]
            else:
                raw_tags = movie.get('tags', [])
                if isinstance(raw_tags, str):
                    raw_tags = raw_tags.replace("'", '"')
                    try: raw_tags = json.loads(raw_tags)
                    except: raw_tags = [raw_tags]
                elif not isinstance(raw_tags, list): raw_tags = []
                b_vec = build_6d_emotion_vector(raw_tags)

                sum_b = sum(b_vec)
                if sum_b > 0:
                    b_vec = [x / sum_b for x in b_vec]

            pure_distance = math.sqrt(sum((t_val - b) ** 2 for t_val, b in zip(target_vec, b_vec)))
            norm_euclidean = _calculate_euclidean(target_vec, b_vec, w_vec)
            cosine_dist = _calculate_cosine(target_vec, b_vec, target_norm)
            emotion_score = (alpha * norm_euclidean) + ((1 - alpha) * cosine_dist)
                
            popularity = float(movie.get('popularity', 0.0) or 0.0)
            popularity_score = min(1.0, popularity / 500.0)
            final_score = (emotion_score * 0.90) + ((1.0 - popularity_score) * 0.10)
            
            if movie.get('genre') in recent_genres:
                final_score += 0.05

            movie_info = {
                'movie_id': int(movie_id) if movie_id.isdigit() else movie_id, 
                'score': round(final_score, 4),
                'pure_distance': pure_distance,
                'genre': movie.get('genre')
            }

            if pure_distance <= radius_limit:
                filtered_and_scored.append(movie_info)
            fallback_list.append(movie_info)

        pool_size = max(top_n * 3, 10)

        if len(filtered_and_scored) >= top_n:
            filtered_and_scored.sort(key=lambda x: x['score'])
            safe_pool = filtered_and_scored[:pool_size]
            is_fallback = False
        else:
            fallback_list.sort(key=lambda x: x['score'])
            safe_pool = fallback_list[:pool_size]
            is_fallback = True
        
        # =========================================================================
        # [안전장치 및 2단계] 치료 임계치 검증 & 취향 정렬
        # =========================================================================
        if user and user.is_authenticated and len(safe_pool) > 0:
            therapeutic_threshold = radius_limit * 0.5
            has_effective_preferred_movie = False

            for item in safe_pool:
                genres = item.get('genre', '')
                pure_dist = item.get('pure_distance', 9.9)
                if genres:
                    genre_list = [g.strip().lower() for g in genres.split(',')]
                    if any(g in liked_movie_genres for g in genre_list):
                        if pure_dist <= therapeutic_threshold:
                            has_effective_preferred_movie = True
                            break

            def get_preference_rank(item):
                final_score = item.get('score', 0.0)

                genres = item.get('genre', '') 
                genre_list = [g.strip().lower() for g in genres.split(',')] if genres else []
                
                # 1. 취향 가산점/패널티 설정
                pref_score = 0
                if any(g in liked_movie_genres for g in genre_list):
                    pref_score = -0.1
                elif any(g in disliked_movie_genres for g in genre_list):
                    pref_score = 0.1
                
                # 2. 최종 정렬값 반환
                return final_score + pref_score

            safe_pool.sort(key=get_preference_rank)

        selected_movies = safe_pool[:top_n]
        movie_ids = [m['movie_id'] for m in selected_movies]
        from daybydaybackend.music_movie.models import Movie
        movie_map = {m.tmdb_id: m for m in Movie.objects.filter(tmdb_id__in=movie_ids)}
        
        recommended_movies = []
        for m in selected_movies:
            mid = m['movie_id']
            if mid in movie_map:
                obj = movie_map[mid]
                obj.score = m['score']
                recommended_movies.append(obj)
                
        return {
            "recommendations": recommended_movies, 
            "is_fallback": is_fallback
        }