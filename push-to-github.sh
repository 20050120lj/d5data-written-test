#!/usr/bin/env bash
# 把本仓库推送到 GitHub（一次性脚本，可重复运行）
#
# 前置：GitHub CLI 已安装（本机已装 2.103.3，路径 C:\Program Files\GitHub CLI）
# 用法：在 Git Bash 里执行  bash push-to-github.sh
#       （第一行会要求你在浏览器输入一次性代码，登录你的 GitHub 账号）

set -euo pipefail
export PATH="$PATH:/c/Program Files/GitHub CLI"

REPO_NAME="${1:-d5data-written-test}"

# 1) 若尚未登录，走设备码登录（浏览器输入一次性代码）
if ! gh auth status > /dev/null 2>&1; then
  echo "==> 需要登录 GitHub，请按提示在浏览器输入一次性代码"
  gh auth login --web --hostname github.com --git-protocol https
fi

echo "==> 当前登录账号："
gh api user --jq .login

# 2) 建仓库并推送（已存在则直接推）
if gh repo view "$REPO_NAME" > /dev/null 2>&1; then
  echo "==> 仓库已存在，直接推送"
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$(gh api user --jq .login)/${REPO_NAME}.git"
  git branch -M main
  git push -u origin main
else
  echo "==> 创建公开仓库 ${REPO_NAME} 并推送"
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push \
    --description "五维数据(d5data)笔试交付：前端 Figma 还原 / SpringBoot 3.2.0 / Playwright+DrissionPage 爬虫 / FastAPI SSE / Agent 评测包审核 / LLM 自动标注"
fi

echo
echo "==> 完成：https://github.com/$(gh api user --jq .login)/${REPO_NAME}"
