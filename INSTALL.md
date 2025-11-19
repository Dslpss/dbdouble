# Guia de Instalação - DBcolor

## Pré-requisitos

### 1. Instalar Python

**Windows:**

1. Baixe o Python 3.11 ou superior de: https://www.python.org/downloads/
2. Durante a instalação, **marque a opção "Add Python to PATH"**
3. Complete a instalação

**Verificar instalação:**
```bash
python --version
# ou
python3 --version
# ou no Windows
py --version
```

### 2. Instalar dependências

Após instalar o Python, instale as dependências do projeto:

```bash
# Navegue até a pasta DBcolor
cd DBcolor

# Instale as dependências
python -m pip install -r requirements.txt

# ou se python não funcionar, tente:
python3 -m pip install -r requirements.txt

# ou no Windows:
py -m pip install -r requirements.txt
```

### 3. Criar ambiente virtual (Recomendado)

É recomendado usar um ambiente virtual para isolar as dependências:

```bash
# Criar ambiente virtual
python -m venv venv

# Ativar ambiente virtual
# Windows (Git Bash):
source venv/Scripts/activate

# Windows (CMD):
venv\Scripts\activate

# Windows (PowerShell):
venv\Scripts\Activate.ps1

# Linux/Mac:
source venv/bin/activate

# Depois de ativar, instalar dependências:
pip install -r requirements.txt
```

### 4. Executar o servidor

```bash
python main.py
```

Ou:

```bash
uvicorn app:app --host 0.0.0.0 --port 3001 --reload
```

## Solução de Problemas

### "pip: command not found"
- Use `python -m pip` em vez de apenas `pip`
- Ou instale o Python novamente marcando "Add Python to PATH"

### "Python was not found"
- Instale o Python de https://www.python.org/downloads/
- Certifique-se de marcar "Add Python to PATH" durante a instalação

### Erro ao instalar dependências
- Atualize o pip: `python -m pip install --upgrade pip`
- Tente instalar individualmente: `python -m pip install fastapi uvicorn websockets python-dotenv`

