import os
import json
import math
from .recommend_movie import _get_target_emotion_vector, _get_direction_weights, _calculate_euclidean, _calculate_cosine, build_6d_emotion_vector
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, 'emotion_tags.json')


class MusicEmotionRecommender:
    def recommend_music(self, user_emotion, music_data, mode='maintain', top_n=3, user=None):
        recent_tags = set()
        liked_music_tags = set()
        disliked_music_tags = set()
        disliked_ids = []

        if user and user.is_authenticated:
            from daybydaybackend.diary.models import DailyRecommended, UserFeedback
            from daybydaybackend.music_movie.models import Music
            from django.contrib.contenttypes.models import ContentType
            from django.utils import timezone
            from datetime import timedelta
            
            recent_recs = DailyRecommended.objects.filter(
                diary__user=user
            ).order_by('-diary__created_at')[:5]
            for rec in recent_recs:
                for ms in rec.musics.all():
                    raw_tags = getattr(ms, 'tags', [])
                    if isinstance(raw_tags, str):
                        raw_tags = raw_tags.replace("'", '"')
                        try: raw_tags = json.loads(raw_tags)
                        except: raw_tags = [raw_tags]
                    elif not isinstance(raw_tags, list): raw_tags = []
                    for t in raw_tags:
                        recent_tags.add(str(t).lower().strip())

            music_type = ContentType.objects.get_for_model(Music)

            liked_ids = UserFeedback.objects.filter(
                user=user, feedback_type='LIKE', content_type=music_type
            ).values_list('object_id', flat=True)
            if liked_ids:
                for m in Music.objects.filter(id__in=liked_ids):
                    rt = m.tags
                    if isinstance(rt, str):
                        rt = rt.replace("'", '"')
                        try: rt = json.loads(rt)
                        except: rt = [rt]
                    elif not isinstance(rt, list): rt = []
                    for t in rt: liked_music_tags.add(str(t).lower().strip())

            # 싫어요 음악 ID 및 기피 태그 수집
            disliked_ids = list(UserFeedback.objects.filter(
                user=user, feedback_type='DISLIKE', content_type=music_type
            ).values_list('object_id', flat=True))

            three_days_ago = timezone.now() - timedelta(days=3)
            recent_disliked_ids = UserFeedback.objects.filter(
                user=user, feedback_type='DISLIKE', content_type=music_type,
                created_at__gte=three_days_ago
            ).values_list('object_id', flat=True)
            if recent_disliked_ids:
                for m in Music.objects.filter(id__in=recent_disliked_ids):
                    rt = m.tags
                    if isinstance(rt, str):
                        rt = rt.replace("'", '"')
                        try: rt = json.loads(rt)
                        except: rt = [rt]
                    elif not isinstance(rt, list): rt = []
                    for t in rt: disliked_music_tags.add(str(t).lower().strip())

        ordered_keys = ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']
        u_vec = [float(user_emotion.get(key, 0.0)) for key in ordered_keys]
        
        target_vec = _get_target_emotion_vector(u_vec, mode)
        target_norm = math.sqrt(sum(t ** 2 for t in target_vec)) or 1e-9
        w_vec = _get_direction_weights(u_vec, mode)
        
        radius_limit = 0.6 if mode == 'maintain' else (1.2 if mode == 'shift' else 0.8)
        alpha = 0.5
        filtered_and_scored = []
        fallback_list = []

        # [1단계] 순수 감정 후보군 추출
        for music in music_data:
            music_id = str(music.get('track_id') or music.get('id'))
            
                
            b_vec = [float(music.get(k, 0.0) or 0.0) for k in ordered_keys]
            raw_tags = music.get('tags', [])
            if isinstance(raw_tags, str):
                raw_tags = raw_tags.replace("'", '"')
                try: raw_tags = json.loads(raw_tags)
                except: raw_tags = [raw_tags]
            elif not isinstance(raw_tags, list): raw_tags = []
                
            if sum(b_vec) < 0.01:
                b_vec = build_6d_emotion_vector(raw_tags)

            sum_b = sum(b_vec)
            if sum_b > 0:
                b_vec = [x / sum_b for x in b_vec]

            pure_distance = math.sqrt(sum((t_val - b) ** 2 for t_val, b in zip(target_vec, b_vec)))
            norm_euclidean = _calculate_euclidean(target_vec, b_vec, w_vec)
            cosine_dist = _calculate_cosine(target_vec, b_vec, target_norm)
            emotion_score = (alpha * norm_euclidean) + ((1 - alpha) * cosine_dist)
                
            popularity = float(music.get('listeners', 0) or 0)
            popularity_score = min(1.0, popularity / 50000000.0)
            final_score = (emotion_score * 0.90) + ((1.0 - popularity_score) * 0.10)
            
            current_tags = [str(t).lower().strip() for t in raw_tags]
            if any(t in recent_tags for t in current_tags):
                final_score += 0.25

            music_info = {
                'track_id': int(music_id) if music_id.isdigit() else music_id, 
                'score': round(final_score, 4),
                'pure_distance': pure_distance,
                'tags': raw_tags
            }

            if pure_distance <= radius_limit:
                filtered_and_scored.append(music_info)
            fallback_list.append(music_info)

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
            has_effective_preferred_music = False

            for item in safe_pool:
                tags = item.get('tags', [])
                pure_dist = item.get('pure_distance', 9.9)
                tag_list = [str(g).lower().strip() for g in tags]
                
                if any(g in liked_music_tags for g in tag_list):
                    if pure_dist <= therapeutic_threshold:
                        has_effective_preferred_music = True
                        break

            # 💡 [books 방식 통일] 완전 배제 대신 패널티 부여!
            def get_preference_rank(item):
                final_score = item.get('score', 0.0)
    
                # 장르 파싱 (구조에 맞춰 'genre' 또는 'tags' 사용)
                raw_tags = item.get('tags', [])
                if isinstance(raw_tags, str):
                    tag_list = [g.strip().lower() for g in raw_tags.split(',')]
                elif isinstance(raw_tags, list):
                    tag_list = [str(g).strip().lower() for g in raw_tags]
                else:
                    tag_list = []

                # 1. 취향 가산점/패널티 설정
                pref_score = 0
                if any(g in liked_music_tags for g in tag_list):
                    pref_score = -0.1
                elif any(g in disliked_music_tags for g in tag_list):
                    pref_score = 0.1
                
                # 2. 최종 정렬값 반환
                return final_score + pref_score

            safe_pool.sort(key=get_preference_rank)

        selected_musics = safe_pool[:top_n]
        music_ids = [m['track_id'] for m in selected_musics]
        from daybydaybackend.music_movie.models import Music
        music_map = {m.id: m for m in Music.objects.filter(id__in=music_ids)}
        
        recommended_musics = []
        for m in selected_musics:
            mid = m['track_id']
            if mid in music_map:
                obj = music_map[mid]
                obj.score = m['score']
                recommended_musics.append(obj)
                
        return {
            "recommendations": recommended_musics, 
            "is_fallback": is_fallback
        }