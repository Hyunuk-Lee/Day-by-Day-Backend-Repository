from django.urls import path
from . import views

app_name = 'diary'

urlpatterns = [
    # 일기 목록 조회 API (전체 최신순)
    path('', views.get_diary_list, name='get_diary_list'),

    # 일기를 작성해서 DB에 저장하는 API
    path('create/', views.create_diary, name='create_diary'),

    # 일기를 ai 한테 보내는 API (Diary + Gemini API 기반 감정 추출)
    path('send/', views.analyze_diary_emotion, name='analyze_diary_emotion'),

    # 캘린더 전용 월별 감정 조회 API (Option A 해시맵 방식)
    path('calendar/', views.get_calendar_view, name='get_calendar_view'),

    # 대시보드용 최근 5개 평균 감정 분석 API
    path('recent-average/', views.get_user_recent_average_emotion_api, name='get_user_recent_average_emotion'),

    # 실시간 공감 멘트 반환 API (Plan C)
    path('empathy/', views.get_diary_empathy_message, name='get_diary_empathy_message'),

    # 단일 일기 상세 조회 API
    path('<int:diary_id>/', views.get_diary_detail, name='get_diary_detail'),

    # 콘텐츠 좋아요/싫어요 피드백 제출 API
    path('feedback/', views.submit_user_feedback, name='submit_user_feedback'),

    # 날짜 기준 일기 검색 API
    path('<str:date>/', views.search_diary_by_date, name='search_diary_by_date'),

    path('account/volatility/', views.update_volatility_view)
]
