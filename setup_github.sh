#!/bin/bash
# AutoQ QEC — Script de integração com GitHub
# Execute este script UMA VEZ na pasta do projeto
# Pré-requisito: git instalado (git --version para verificar)

set -e  # para se der erro

echo "=============================================="
echo "  AutoQ QEC — Integração GitHub"
echo "=============================================="

# 1. Verificar se git está instalado
if ! command -v git &> /dev/null; then
    echo "ERRO: git não encontrado."
    echo "Instale em: https://git-scm.com/downloads"
    exit 1
fi
echo "✓ git encontrado: $(git --version)"

# 2. Verificar se estamos na pasta correta
if [ ! -f "pyproject.toml" ]; then
    echo "ERRO: Execute este script dentro da pasta autoq_qec/"
    exit 1
fi
echo "✓ pyproject.toml encontrado"

# 3. Configurar identidade git (se ainda não configurado)
if [ -z "$(git config --global user.email)" ]; then
    echo ""
    echo "Configure seu nome e email para o git:"
    read -p "  Seu nome: " GIT_NAME
    read -p "  Seu email: " GIT_EMAIL
    git config --global user.name "$GIT_NAME"
    git config --global user.email "$GIT_EMAIL"
    echo "✓ Identidade configurada"
fi

# 4. Inicializar repositório
if [ ! -d ".git" ]; then
    git init
    git branch -M main
    echo "✓ Repositório git inicializado"
else
    echo "✓ Repositório git já existe"
fi

# 5. Adicionar todos os arquivos
git add .
git status --short

# 6. Commit inicial
if git diff --cached --quiet; then
    echo "✓ Nada para commitar (já está em dia)"
else
    git commit -m "feat: initial release — multi-code QEC estimator v0.1.0

- QEC estimator: Surface Code (Fowler 2012), Bacon-Shor, Steane [[7,1,3]]
- Real hardware profiles: IBM Eagle/Heron, Quantinuum H2, IonQ Aria
- IBM live calibration via qiskit-ibm-runtime
- Recommender with weighted ranking
- 22 physics-verifying tests (22/22 passing)"
    echo "✓ Commit inicial criado"
fi

# 7. Instruções para conectar ao GitHub
echo ""
echo "=============================================="
echo "  PRÓXIMOS PASSOS (fazer no navegador + terminal)"
echo "=============================================="
echo ""
echo "PASSO 1 — Criar repositório no GitHub:"
echo "  1. Abrir: https://github.com/new"
echo "  2. Repository name: autoq-qec"
echo "  3. Description: Multi-code QEC resource estimator for Qiskit circuits"
echo "  4. Deixar: Public"
echo "  5. NÃO marcar: Add README, Add .gitignore, Choose license"
echo "     (já temos todos esses arquivos)"
echo "  6. Clicar: Create repository"
echo ""
echo "PASSO 2 — Copiar a URL que o GitHub mostrar e rodar:"
echo ""
echo "  git remote add origin https://github.com/SEU_USUARIO/autoq-qec.git"
echo "  git push -u origin main"
echo ""
echo "  (GitHub vai pedir seu usuário e senha/token)"
echo "  Se pedir token: github.com → Settings → Developer Settings"
echo "                              → Personal Access Tokens → Tokens (classic)"
echo "                              → Generate new token → marcar 'repo' → copiar"
echo ""
echo "PASSO 3 — Verificar que o CI rodou:"
echo "  Acessar: https://github.com/SEU_USUARIO/autoq-qec/actions"
echo "  O workflow 'CI' deve aparecer verde em ~2 minutos"
