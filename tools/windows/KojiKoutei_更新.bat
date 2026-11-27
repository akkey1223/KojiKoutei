@echo off
rem ==========================================================================
rem  KojiKoutei（工事工程アプリ・日当り抽出アプリ）を GitHub の最新にそろえる
rem   1. 初回は GitHub から PC にコピー（clone）、2回目からは最新を取り込み（pull）
rem   2. Python が入っていれば、日当り抽出アプリの部品をそろえる（pip）
rem   3. SHARE を設定していれば、共有フォルダへ工程アプリと日当りマスタを配る
rem  PC 側でファイルを書き換えていると取り込みを止めます（上書きはしません）
rem ==========================================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion

rem ---- 設定（必要に応じて書き換え） ----
set "REPO=%USERPROFILE%\Documents\KojiKoutei"
rem 共有フォルダ（例：\\fileserver\共有\工程管理）。空のままなら配布はしません
set "SHARE="
set "LOG=%LOCALAPPDATA%\KojiKoutei_更新ログ.txt"

echo.>>"%LOG%"
echo ===== %date% %time% =====>>"%LOG%"

where git >nul 2>nul
if errorlevel 1 (
  echo Git が入っていません。Git for Windows を入れてから実行してください。
  echo Git が入っていません>>"%LOG%"
  exit /b 1
)

if not exist "%REPO%\.git" (
  echo GitHub から PC にコピーしています…（初回はブラウザで GitHub へのログインを求められます）
  git clone https://github.com/akkey1223/KojiKoutei.git "%REPO%" >>"%LOG%" 2>&1
  if errorlevel 1 ( echo コピーできませんでした。ログ：%LOG% & exit /b 1 )
)

cd /d "%REPO%"
for /f %%h in ('git rev-parse HEAD') do set "OLD=%%h"
git pull --ff-only >>"%LOG%" 2>&1
if errorlevel 1 (
  echo 最新を取り込めませんでした。PC 側でファイルを書き換えていないか確かめてください。ログ：%LOG%
  exit /b 1
)
for /f %%h in ('git rev-parse HEAD') do set "NEW=%%h"
if "%OLD%"=="%NEW%" (
  echo 最新の状態です。
  echo 変更なし>>"%LOG%"
) else (
  echo 最新を取り込みました。
  git log --oneline %OLD%..%NEW% >>"%LOG%" 2>&1
)

rem ---- 日当り抽出アプリの部品（Python があるときだけ） ----
where python >nul 2>nul
if not errorlevel 1 (
  python -m pip install --user -q -r "%REPO%\bugakari\requirements.txt" >>"%LOG%" 2>&1
)

rem ---- 共有フォルダへの配布（SHARE を設定したときだけ） ----
if defined SHARE (
  if exist "%SHARE%\" (
    copy /y "%REPO%\app\工事工程表.html" "%SHARE%\工事工程表.html" >>"%LOG%" 2>&1
    for %%f in ("%REPO%\bugakari\data\R??_日当り.json") do (
      set "N=%%~nf"
      copy /y "%%f" "%SHARE%\_日当りマスタ_!N:~0,3!.json" >>"%LOG%" 2>&1
    )
    echo 共有フォルダへ配りました：%SHARE%
  ) else (
    echo 共有フォルダが見つかりません：%SHARE%
    echo 共有フォルダが見つかりません：%SHARE%>>"%LOG%"
  )
)
endlocal
exit /b 0
