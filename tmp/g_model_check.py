import google.generativeai as genai

# 1. 본인의 API 키를 여기에 입력하세요.
GOOGLE_API_KEY = "YOUR_API_KEY_HERE"

# 2. API 키 설정
genai.configure(api_key=GOOGLE_API_KEY)

def list_available_models():
    try:
        print("사용 가능한 Gemini 모델 목록을 불러오는 중입니다...\n")
        
        # 3. 모델 목록 가져오기
        # 'list_models' 메서드는 현재 사용 가능한 모델 객체들을 반환합니다.
        for model in genai.list_models():
            # 'generateContent' 기능을 지원하는 모델만 필터링해서 보여주면 더 깔끔해요.
            if 'generateContent' in model.supported_generation_methods:
                print(f"모델 이름: {model.name}")
                print(f"표시 이름: {model.display_name}")
                print(f"설명: {model.description}")
                print("-" * 50)
                
    except Exception as e:
        print(f"오류가 발생했어요: {e}")

if __name__ == "__main__":
    list_available_models()