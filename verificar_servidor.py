"""
Script para verificar se o servidor está servindo HTML corretamente
Execute este script enquanto o servidor está rodando
"""
import requests
import sys

try:
    print("🔍 Testando servidor em http://localhost:3001/...")
    
    # Testar endpoint raiz
    response = requests.get("http://localhost:3001/", timeout=5)
    
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
    print(f"\nPrimeiros 500 caracteres da resposta:")
    print("-" * 50)
    print(response.text[:500])
    print("-" * 50)
    
    if "text/html" in response.headers.get("Content-Type", ""):
        if "<!DOCTYPE html>" in response.text or "<html" in response.text:
            print("\n✅ SUCESSO! Servidor está servindo HTML corretamente!")
        else:
            print("\n⚠️ Content-Type é HTML mas conteúdo não parece ser HTML válido")
    else:
        print("\n❌ ERRO! Servidor está retornando JSON em vez de HTML")
        try:
            json_data = response.json()
            print(f"Resposta JSON: {json_data}")
        except:
            pass
    
    # Testar endpoint /api
    print("\n" + "="*50)
    print("Testando endpoint /api...")
    api_response = requests.get("http://localhost:3001/api", timeout=5)
    print(f"Status: {api_response.status_code}")
    try:
        api_data = api_response.json()
        print(f"Service: {api_data.get('service', 'N/A')}")
    except:
        print("Resposta não é JSON válido")
        
except requests.exceptions.ConnectionError:
    print("❌ ERRO: Não foi possível conectar ao servidor!")
    print("Certifique-se de que o servidor está rodando em http://localhost:3001")
    sys.exit(1)
except Exception as e:
    print(f"❌ ERRO: {e}")
    sys.exit(1)



