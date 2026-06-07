from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .models import UserProfile

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['emotion_volatility']

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(source='userprofile', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'profile']


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    유저 정보 수정 허용 필드 정의 (확장성 고려)
    - username은 수정 불가 처리 (fields에 미포함)
    - 비밀번호는 write_only로 설정하여 노출 방지
    """
    class Meta:
        model = User
        fields = ['email', 'password']
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'email': {'required': False}
        }


class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('username', 'password', 'email')
        extra_kwargs = {'password': {'write_only': True}}  # 비밀번호는 읽기 금지


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data.get("username"), password=data.get("password"))
        if user and user.is_active:
            return user
        raise serializers.ValidationError("아이디 또는 비밀번호가 올바르지 않습니다.")
