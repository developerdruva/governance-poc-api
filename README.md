# governance-poc-api

find . -type d -name "**pycache**" -exec rm -r {} +

export PYTHONDONTWRITEBYTECODE=1 or 0 (1 not create, 0 for create) (do it in bash)

uvicorn main:app --reload
