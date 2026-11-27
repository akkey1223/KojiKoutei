@echo off
rem 「KojiKoutei_更新.bat」を毎日 8:15 に自動で実行するよう、Windows のタスク スケジューラに登録します
rem （このファイルと KojiKoutei_更新.bat を同じフォルダに置いてから実行してください）
chcp 65001 >nul
set "BAT=%~dp0KojiKoutei_更新.bat"
if not exist "%BAT%" ( echo KojiKoutei_更新.bat が同じフォルダにありません & pause & exit /b 1 )
schtasks /create /f /tn "KojiKoutei 自動更新" /tr "\"%BAT%\"" /sc daily /st 08:15
if errorlevel 1 ( echo 登録できませんでした & pause & exit /b 1 )
echo 登録しました。毎日 8:15 に最新を取り込みます。
echo すぐに試すときは KojiKoutei_更新.bat をダブルクリックしてください。
echo 登録を消すときは：schtasks /delete /tn "KojiKoutei 自動更新" /f
pause
