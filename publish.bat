@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  a-shares-analysis 一键发布脚本（gh skill publish 通道）
rem  用法：publish.bat v0.1.1   或   publish.bat（交互输入版本号）
rem  流程：测试 -> 提交 -> 推送 -> gh skill publish（自动打 agent-skills 话题并建 release）
rem ============================================================

set "PUB=G:\AIcoding\my-skills\A-shares-analysis"
set "SKILL_DIR=%PUB%\skills\a-shares-analysis"
set "REPO=OwenTrader/a-shares-analysis"
set "BRANCH=main"
set "PY=%SKILL_DIR%\.venv\Scripts\python.exe"

echo.
echo === a-shares-analysis 发布脚本 ===
echo 仓库: %REPO%  分支: %BRANCH%
echo.

if not exist "%SKILL_DIR%\SKILL.md" (
  echo [错误] 找不到技能入口: %SKILL_DIR%\SKILL.md
  goto :fail
)

echo [1/5] 运行离线测试...
pushd "%SKILL_DIR%"
"%PY%" -m pytest tests -q
if errorlevel 1 (
  popd
  echo [错误] 测试未通过，中止发布
  goto :fail
)
popd

echo [2/5] 提交仓库变更...
pushd "%PUB%"
git add -A
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "chore: sync skill content from working tree"
  if errorlevel 1 ( popd & echo [错误] 提交失败 & goto :fail )
  echo       已提交新变更
) else (
  echo       无文件变更，跳过提交
)

echo [3/5] 推送到 GitHub...
git push origin %BRANCH%
if errorlevel 1 (
  echo       首次推送失败，重试...
  timeout /t 5 /nobreak >nul
  git push origin %BRANCH%
  if errorlevel 1 (
    popd
    echo [错误] 推送失败（网络/代理），中止发布以免旧代码进 release
    goto :fail
  )
)
popd

echo [4/5] 校验远程与本地一致...
pushd "%PUB%"
for /f "usebackq delims=" %%i in (`git rev-parse HEAD`) do set "LOCAL_SHA=%%i"
popd
for /f "usebackq delims=" %%i in (`gh api repos/%REPO%/commits/%BRANCH% --jq .sha`) do set "REMOTE_SHA=%%i"
if not "%LOCAL_SHA%"=="%REMOTE_SHA%" (
  echo       [错误] 远程与本地不一致: %LOCAL_SHA:~0,7% vs %REMOTE_SHA:~0,7%
  goto :fail
)
echo       一致 OK

echo [5/5] gh skill publish ...
set "TAG=%~1"
if "%TAG%"=="" set /p TAG=请输入版本号（例如 v0.1.1，直接回车取消）:
if "%TAG%"=="" (
  echo 未输入版本号，已取消（同步与提交已完成）
  goto :end
)
gh skill publish --tag %TAG%
if errorlevel 1 (
  echo [错误] skill 发布失败
  goto :fail
)

echo.
echo === 发布完成 ===
echo https://github.com/%REPO%/releases/tag/%TAG%
echo 安装: gh skill install %REPO%
goto :end

:fail
echo === 脚本中止 ===
exit /b 1

:end
endlocal
exit /b 0
