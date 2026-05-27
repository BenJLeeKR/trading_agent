from openai import OpenAI

# DeepSeek 클라이언트 설정
client = OpenAI(
    api_key="sk-9890520cb52641bd9160ad1b57f76186", 
    base_url="https://api.deepseek.com"
)

def list_deepseek_models():
    print("--- 사용 가능한 DeepSeek 모델 목록 ---")
    try:
        # 모델 목록 가져오기
        models = client.models.list()
        
        for model in models:
            print(f"Model ID: {model.id}")
            # 생성된 시간 등 추가 정보가 필요하다면 model.created 등을 출력할 수 있어요.
    except Exception as e:
        print(f"에러가 발생했어요: {e}")

if __name__ == "__main__":
    list_deepseek_models()