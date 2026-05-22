import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

class EmotionAnalyzer:
    def __init__(self):
        # 외부 Kiwi 분석 마이크로서비스 주소 로드 (끝자리에 슬래시 보장)
        self.api_url = getattr(settings, 'KIWI_ANALYZER_URL', 'http://localhost:8001/')
        if not self.api_url.endswith('/'):
            self.api_url += '/'
        self.analyze_endpoint = f"{self.api_url}api/analyze/"
        logger.info(f"EmotionAnalyzer initialized. Remote Server: {self.analyze_endpoint}")

    def analyze(self, text: str) -> dict:
        """
        외부 Kiwi 형태소 분석 전용 Django 서버에 분석 요청을 보내고 6차원 감정 수치를 받아옵니다.
        """
        if not text or not text.strip():
            return self._empty_emotions()

        try:
            # 외부 마이크로서비스 호출 (POST 방식)
            response = requests.post(
                self.analyze_endpoint,
                json={"text": text},
                timeout=10  # 10초 타임아웃 지정
            )

            if response.status_code == 200:
                result = response.json()
                # 정상 반환된 감정 데이터를 안정적으로 캐스팅하여 리턴
                return {
                    "joy": float(result.get("joy", 0.0)),
                    "sadness": float(result.get("sadness", 0.0)),
                    "anger": float(result.get("anger", 0.0)),
                    "fear": float(result.get("fear", 0.0)),
                    "trust": float(result.get("trust", 0.0)),
                    "surprise": float(result.get("surprise", 0.0)),
                    "valence": float(result.get("valence", 0.0)),
                    "arousal": float(result.get("arousal", 0.0)),
                    "primary_emotion": str(result.get("primary_emotion", "알수없음"))
                }
            else:
                logger.error(f"Remote Kiwi Analyzer returned status {response.status_code}: {response.text}")
                return self._empty_emotions()

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to communicate with remote Kiwi Analyzer: {e}")
            return self._empty_emotions()

    def _empty_emotions(self) -> dict:
        return {
            "joy": 0.0,
            "sadness": 0.0,
            "anger": 0.0,
            "fear": 0.0,
            "trust": 0.0,
            "surprise": 0.0,
            "valence": 0.0,
            "arousal": 0.0,
            "primary_emotion": "알수없음"
        }
