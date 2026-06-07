import json
import os
import math

from daybydaybackend.diary.models import Diary, DailyRecommended
from daybydaybackend.music_movie.models import Music, Movie
from .recommend_music_movie.recommend_music import MusicEmotionRecommender
from .recommend_music_movie.recommend_movie import MovieEmotionRecommender

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recommend_music_movie')

_cached_music_data = None
_cached_movie_data = None

def load_music_data():
    global _cached_music_data
    if _cached_music_data is None:
        db_music = Music.objects.all().values(
            'id', 'title', 'artist', 'source_tag', 'listeners', 
            'playcount', 'image_url', 'tags', 
            'valence', 'arousal', 'joy', 'sadness', 'anger', 'fear', 'trust', 'surprise'
        )
        _cached_music_data = []
        for m in db_music:
            # 벡터 추출
            vec = [m.get(k, 0.0) or 0.0 for k in ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']]
            sum_v = sum(vec)
            if sum_v > 0:
                # 정규화된 값을 캐시에 저장
                for i, k in enumerate(['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']):
                    m[k] = vec[i] / sum_v
            m['track_id'] = m['id']
            _cached_music_data.append(m)
    return _cached_music_data

def load_movie_data():
    global _cached_movie_data
    if _cached_movie_data is None:
        db_movie = Movie.objects.all().values(
            'tmdb_id', 'title', 'genre', 'overview', 'vote_average', 
            'vote_count', 'popularity', 'release_date', 'poster_path', 
            'valence', 'arousal', 'joy', 'sadness', 'anger', 'fear', 'trust', 'surprise'
        )
        _cached_movie_data = []
        for m in db_movie:
            # 벡터 추출
            vec = [m.get(k, 0.0) or 0.0 for k in ['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']]
            sum_v = sum(vec)
            if sum_v > 0:
                # 정규화된 값을 캐시에 저장
                for i, k in enumerate(['joy', 'sadness', 'anger', 'fear', 'trust', 'surprise']):
                    m[k] = vec[i] / sum_v
            m['movie_id'] = m['tmdb_id']
            _cached_movie_data.append(m)
    return _cached_movie_data

def clear_content_cache():
    global _cached_music_data, _cached_movie_data
    _cached_music_data = None
    _cached_movie_data = None

def convert_emotion_to_6d_vector(emotion_vector: dict) -> dict:
    joy = emotion_vector.get('joy', 0) * 1.0 + emotion_vector.get('romance', 0) * 0.6
    sadness = emotion_vector.get('sadness', 0) * 1.0 + emotion_vector.get('darkness', 0) * 0.5
    anger = emotion_vector.get('anger', 0) * 1.0
    fear = emotion_vector.get('fear', 0) * 1.0 + emotion_vector.get('darkness', 0) * 0.3
    trust = emotion_vector.get('trust', 0) * 1.0 + emotion_vector.get('calmness', 0) * 0.8
    surprise = emotion_vector.get('surprise', 0) * 1.0 + emotion_vector.get('energy', 0) * 0.5
    return {
        'joy': round(max(0.0, min(1.0, joy)), 2), 'sadness': round(max(0.0, min(1.0, sadness)), 2),
        'anger': round(max(0.0, min(1.0, anger)), 2), 'fear': round(max(0.0, min(1.0, fear)), 2),
        'trust': round(max(0.0, min(1.0, trust)), 2), 'surprise': round(max(0.0, min(1.0, surprise)), 2),
    }

def _attach_scores(instances, diary_obj, mode, is_movie=False):
    if not instances:
        return instances
        
    raw_e = getattr(diary_obj, 'emotion', None)
    u_vec = [
        getattr(raw_e, 'joy', 0.0), getattr(raw_e, 'sadness', 0.0), 
        getattr(raw_e, 'anger', 0.0), getattr(raw_e, 'fear', 0.0), 
        getattr(raw_e, 'trust', 0.0), getattr(raw_e, 'surprise', 0.0)
    ]
    
    if is_movie:
        from .recommend_music_movie.recommend_movie import _get_target_emotion_vector, _get_direction_weights, _calculate_euclidean, _calculate_cosine, build_6d_emotion_vector
    else:
        from .recommend_music_movie.recommend_music import _get_target_emotion_vector, _get_direction_weights, _calculate_euclidean, _calculate_cosine, build_6d_emotion_vector
    
    target_vec = _get_target_emotion_vector(u_vec, mode)
    target_norm = math.sqrt(sum(t ** 2 for t in target_vec)) or 1e-9    
    w_vec = _get_direction_weights(u_vec, mode)

    if mode == 'maintain': alpha = 0.90
    elif mode == 'amplification': alpha = 0.80
    else: alpha = 0.30

    for item in instances:
        b_vec = [
            getattr(item, 'joy', 0.0), getattr(item, 'sadness', 0.0), 
            getattr(item, 'anger', 0.0), getattr(item, 'fear', 0.0), 
            getattr(item, 'trust', 0.0), getattr(item, 'surprise', 0.0)
        ]
        
        if sum(b_vec) < 0.01:
            if is_movie:
                raw_tags = [item.genre] if getattr(item, 'genre', None) else []
            else:
                raw_tags = getattr(item, 'tags', [])
                if isinstance(raw_tags, str):
                    raw_tags = raw_tags.replace("'", '"')
                    try: raw_tags = json.loads(raw_tags)
                    except: raw_tags = [raw_tags]
                elif not isinstance(raw_tags, list):
                    raw_tags = []
            b_vec = build_6d_emotion_vector(raw_tags)
            
        sum_b = sum(b_vec)
        if sum_b > 0:
            b_vec = [x / sum_b for x in b_vec]
            
        norm_euclidean = _calculate_euclidean(target_vec, b_vec, w_vec)
        cosine_dist = _calculate_cosine(target_vec, b_vec, target_norm)
        emotion_score = (alpha * norm_euclidean) + ((1 - alpha) * cosine_dist)
        
        if is_movie:
            popularity = float(getattr(item, 'popularity', 0.0) or 0.0)
            popularity_score = min(1.0, popularity / 500.0)
        else:
            popularity = float(getattr(item, 'listeners', 0) or 0)
            popularity_score = min(1.0, popularity / 50000000.0)
            
        final_score = (emotion_score * 0.95) + ((1.0 - popularity_score) * 0.05)
        item.score = round(final_score, 4)
        
    return instances

def get_or_create_music_recommendation(diary_obj, user_emotion: dict, mode: str, count: int):
    daily_rec, created = DailyRecommended.objects.get_or_create(diary=diary_obj, mode=mode)
    saved_count = daily_rec.musics.count()

    if created or saved_count == 0 or saved_count < count:
        music_data = load_music_data()
        recommender = MusicEmotionRecommender()
        
        # 💡 user 객체 전달 
        res = recommender.recommend_music(user_emotion, music_data, mode=mode, top_n=count, user=diary_obj.user)
        
        music_instances = res.get('recommendations', [])
        is_fallback = res.get('is_fallback', False) 
        
        daily_rec.musics.set(music_instances)
        
        # 💡 Fallback 상태 저장
        daily_rec.is_music_fallback = is_fallback
        daily_rec.save(update_fields=['is_music_fallback'])
            
    else:
        music_instances = list(daily_rec.musics.all()[:count])
        _attach_scores(music_instances, diary_obj, mode, is_movie=False)
        is_fallback = daily_rec.is_music_fallback 
        
    return music_instances, is_fallback

def get_or_create_movie_recommendation(diary_obj, user_emotion: dict, mode: str, count: int):
    daily_rec, created = DailyRecommended.objects.get_or_create(diary=diary_obj, mode=mode)
    saved_count = daily_rec.movies.count()

    if created or saved_count == 0 or saved_count < count:
        movie_data = load_movie_data()
        for movie in movie_data:
            if isinstance(movie.get("genre"), list):
                movie["genre"] = ", ".join(movie["genre"])
        recommender = MovieEmotionRecommender()
        
        # 💡 user 객체 전달 
        res = recommender.recommend_movies(user_emotion, movie_data, mode=mode, top_n=count, user=diary_obj.user)

        movie_instances = res.get('recommendations', [])
        is_fallback = res.get('is_fallback', False)

        daily_rec.movies.set(movie_instances)
        
        # 💡 Fallback 상태 저장
        daily_rec.is_movie_fallback = is_fallback
        daily_rec.save(update_fields=['is_movie_fallback'])

    else:
        movie_instances = list(daily_rec.movies.all()[:count])
        _attach_scores(movie_instances, diary_obj, mode, is_movie=True)
        is_fallback = daily_rec.is_movie_fallback
    
    return movie_instances, is_fallback

def get_saved_music_metadata(diary_obj):
    daily_recs = DailyRecommended.objects.filter(diary=diary_obj).prefetch_related('musics')
    result = []
    for rec in daily_recs:
        scored_musics = _attach_scores(rec.musics.all(), diary_obj, rec.mode, is_movie=False)
        formatted_musics = []
        for m in scored_musics:
            artist = getattr(m, 'artist', '')
            title = getattr(m, 'title', '')
            external_url = f"https://www.last.fm/search?q={artist}+{title}".replace(" ", "+") if artist and title else "https://www.last.fm/"
            
            formatted_musics.append({
                'track_id': m.id,
                'title': title,
                'artist': artist if artist else '아티스트 미상',
                'image_url': getattr(m, 'image_url', ''),
                'tags': m.tags if isinstance(m.tags, list) else [],
                'score': getattr(m, 'score', 0.0),
                'external_url': external_url
            })
        result.append({'mode': rec.mode, 'musics': formatted_musics})
    return result

def get_saved_movie_metadata(diary_obj):
    daily_recs = DailyRecommended.objects.filter(diary=diary_obj).prefetch_related('movies')
    result = []
    for rec in daily_recs:
        scored_movies = _attach_scores(rec.movies.all(), diary_obj, rec.mode, is_movie=True)
        formatted_movies = []
        for m in scored_movies:
            movie_id = getattr(m, 'tmdb_id', None)
            external_url = f"https://www.themoviedb.org/movie/{movie_id}" if movie_id else "https://www.themoviedb.org/"
            
            formatted_movies.append({
                'movie_id': movie_id,
                'title': getattr(m, 'title', ''),
                'director': getattr(m, 'director', '감독 정보 없음'),
                'image_url': getattr(m, 'poster_path', ''),
                'tags': [m.genre] if getattr(m, 'genre', None) else [],
                'score': getattr(m, 'score', 0.0),
                'external_url': external_url
            })
        result.append({'mode': rec.mode, 'movies': formatted_movies})
    return result