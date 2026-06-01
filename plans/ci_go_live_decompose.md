# CI 鍏ㄩ潰涓婄嚎鍒嗚В鏂规

> **缂栧埗**锛氬ⅷ琛?| **鐗堟湰**锛歷1.0 | **鏃ユ湡**锛?026-06-01
>
> **P0 宸ヤ綔椤?*锛歐I 2 鈥?鍥炲綊娴嬭瘯濂椾欢锛?23+ 鐢ㄤ緥锛塁I 宓屽叆 鈫?CI 鍏ㄩ潰涓婄嚎
>
> **鎬诲伐鏈?*锛氱害 2 澶╋紙宸ヤ綔鏃ワ級锛屼笌 Week 2锛?6/08~06/14锛夊榻?>
> **寮曠敤**锛歚docs/07_research/plans/verify_next_steps_20260601.md`銆乣docs/07_research/plans/ci_run_guide.md`
>
> **绾︽潫**锛?> - 姣忎釜瀛愪换鍔?鈮?15 鍒嗛挓
> - 涓茶渚濊禆閾炬竻鏅?> - 澧ㄨ惐瑕佹眰锛欳I 澶辫触闃绘鍚堝苟

---

## 渚濊禆閾炬€昏

```
T1 鈹€鈫?T2 鈹€鈫?T3 鈹€鈫?T4 鈹€鈫?T5 鈹€鈫?T6 鈹€鈫?T7
                                      鈹?                                      鈹斺啋 T8 鈹€鈫?T9 鈹€鈫?T10

T1: 浠撳簱杩滅▼閰嶇疆              T6: 瑙﹀彂 CI 杩愯锛堟墜鍔ㄦ帹閫侊級
T2: GitHub 浠撳簱鍒涘缓           T7: 瑙傚療棣栨 CI 缁撴灉
T3: 鑷墭绠?Runner 瀹夎        T8: 鈽?淇 CI 澶辫触锛堝惊鐜紝鈮?娆★級
T4: Runner 娉ㄥ唽涓庨厤缃?        T9: 鍒嗘敮淇濇姢绛栫暐閰嶇疆
T5: GitHub Actions 宸ヤ綔娴佹枃浠? T10: 椋炰功閫氱煡楠岃瘉
```

**鍏抽敭璺緞**锛歍1 鈫?T2 鈫?T3 鈫?T4 鈫?T5 鈫?T6 鈫?T7 鈫?(T8 寰幆) 鈫?T9 鈫?T10

**骞惰鍒嗘敮**锛歍5锛堝伐浣滄祦鏂囦欢寮€鍙戯級鍙彁鍓嶅湪鏈湴缂栧啓锛屼笌 T3/T4 骞惰

---

## 瀛愪换鍔¤鎯?
### T1锛氫粨搴撹繙绋嬮厤缃?
| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 閰嶇疆 GitHub 杩滅▼浠撳簱鍦板潃 |
| **棰勪及鑰楁椂** | 5 min |
| **渚濊禆** | 鏃?|
| **鎻忚堪** | 褰撳墠 mozhi_platform 浠撳簱浠呮湁鏈湴 master 鍒嗘敮锛屾棤杩滅▼閰嶇疆銆傞渶鍏堝湪 GitHub 鏂板缓绌轰粨搴擄紝鐒跺悗娣诲姞 remote origin 骞舵帹閫併€?|
| **鎿嶄綔姝ラ** | 1. 纭畾 GitHub 缁勭粐/鐢ㄦ埛鍚嶏紙濡?`mozhi-investment`锛?br>2. 纭畾浠撳簱鍚嶏紙濡?`mozhi-platform`锛?br>3. `git remote add origin https://github.com/<org>/<repo>.git` |
| **楠屾敹鏍囧噯** | `git remote -v` 杈撳嚭 origin 鐨?fetch/push URL锛岃繑鍥炲€?0 |
| **椋庨櫓** | 鏃?|

---

### T2锛欸itHub 浠撳簱鍒涘缓

| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 鍦?GitHub 涓婂垱寤虹┖浠撳簱 |
| **棰勪及鑰楁椂** | 10 min |
| **渚濊禆** | T1锛堥渶瑕佽繙绋?URL锛?|
| **鎻忚堪** | 閫氳繃 GitHub CLI 鎴?Web 鐣岄潰鍒涘缓绌轰粨搴擄紙涓嶈鍕鹃€夊垵濮嬪寲 README / LICENSE / .gitignore锛夛紝淇濇寔鏈湴浠撳簱浣滀负 source of truth銆?|
| **鎿嶄綔姝ラ** | 1. 浣跨敤 GitHub CLI: `gh repo create <org>/<repo> --private --push --source . --remote origin`<br>2. 鎴栨祻瑙堝櫒鍒涘缓鍚庢墜鍔?push<br>3. 鍒濆鎺ㄩ€侊細`git push -u origin master` |
| **楠屾敹鏍囧噯** | `git push origin master` 鎴愬姛锛孏itHub 椤甸潰涓婅兘鐪嬪埌浠撳簱鍐呭 |
| **椋庨櫓** | 闇€瑕?GitHub 璐﹀彿鏉冮檺锛涜嫢鏃犳硶鍒涘缓 Public 浠撳簱锛屼娇鐢?Private 浠撳簱 |

---

### T3锛氳嚜鎵樼 Runner 瀹夎

| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 瀹夎 GitHub Actions 鑷墭绠?Runner |
| **棰勪及鑰楁椂** | 15 min |
| **渚濊禆** | T2锛堥渶瑕佷粨搴撳氨缁互鑾峰彇 Runner token锛?|
| **鎻忚堪** | 鍦ㄦ湰鍦板紑鍙戞満锛坒zm-zenbook锛夊畨瑁?GitHub Actions 鑷墭绠?Runner銆傚綋鍓嶆満鍣ㄤ粎 1.5GB 鍙敤鍐呭瓨锛岄渶瑕佽瘎浼版槸鍚﹁兘鍦ㄦ湰鍦拌窇 CI銆傝嫢鍐呭瓨涓嶈冻锛岃€冭檻澶囬€夋柟妗堛€?|
| **鎿嶄綔姝ラ** | 1. 浠?GitHub 浠撳簱 Settings 鈫?Actions 鈫?Runners 鈫?New self-hosted runner 鑾峰彇 token<br>2. 涓嬭浇 runner 鍖咃細`curl -o actions-runner-win-x64.zip <url>`<br>3. 瑙ｅ帇鍒?`C:\actions-runner\`<br>4. 閰嶇疆锛歚.\config.cmd --url https://github.com/<org>/<repo> --token <token>`<br>5. 瀹夎鏈嶅姟锛歚.\svc.cmd install`<br>6. 鍚姩锛歚.\svc.cmd start` |
| **楠屾敹鏍囧噯** | Runner 鍦?GitHub 浠撳簱 Settings 鈫?Actions 鈫?Runners 涓樉绀轰负缁胯壊 "Idle" |
| **椋庨櫓** | **鈿狅笍 楂?*锛氭満鍣ㄤ粎 1.5GB 鍙敤鍐呭瓨銆傝嫢 CI 瀹屾暣鍥炲綊鎵ц鏃?OOM锛岄渶瑕佸垏鎹㈡柟妗堬細<br>1. 闄嶈嚦 0.5GB 铏氭嫙鍐呭瓨涓寸晫鐐?鈫?閲囩敤鍒嗘壒鎵ц绛栫暐锛圥R 绾?5min 鍏ㄩ儴璺戝畬锛屾瘡鏃ョ骇鍒嗘垚 3 鎵规瘡娆?10min锛?br>2. 瀹屽叏鏃犳硶鎵垮彈 鈫?杩佺Щ鑷充綆閰?Runner锛堝鍙︿竴鍙扮┖闂叉満鍣級<br>3. 鏋佺鎯呭喌 鈫?閲囩敤鏈湴 CRON + 椋炰功閫氱煡鏇夸唬 CI锛堝洖閫€鏂规锛?|

---

### T4锛歊unner 娉ㄥ唽涓庨厤缃?
| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 瀹屾垚 Runner 娉ㄥ唽涓庡伐浣滄爣绛?|
| **棰勪及鑰楁椂** | 5 min |
| **渚濊禆** | T3锛圧unner 瀹夎瀹屾垚锛?|
| **鎻忚堪** | 涓?Runner 閰嶇疆鏍囩鍜屽垎缁勶紝纭繚鍚庣画宸ヤ綔娴佸彧鍖归厤鍒版纭殑 Runner銆?|
| **鎿嶄綔姝ラ** | 1. 鍦?`config.cmd` 鎴栭€氳繃 Settings 椤甸潰娣诲姞鏍囩锛歚windows`, `self-hosted`, `fzm-zenbook`<br>2. 楠岃瘉 Runner 鍙帴鏀朵换鍔★細`.\run.cmd` 鎵嬪姩鍚姩涓€娆?br>3. 纭 Runner 缁勶紙榛樿涓?Default锛?|
| **楠屾敹鏍囧噯** | `gh api /repos/<org>/<repo>/actions/runners` 杩斿洖鐨?runner 鐘舵€佷负 `online` |
| **椋庨櫓** | 浣?|

---

### T5锛欸itHub Actions 宸ヤ綔娴佹枃浠剁紪鍐?
| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 缂栧啓 .github/workflows/ CI 宸ヤ綔娴?YAML |
| **棰勪及鑰楁椂** | 15 min |
| **渚濊禆** | 鏃狅紙鍙笌 T3/T4 骞惰锛?|
| **鎻忚堪** | 鍒涘缓 `mozhi_platform/.github/workflows/` 鐩綍锛岀紪鍐欏垎灞?CI 宸ヤ綔娴佹枃浠躲€傚弬鑰?`ci_run_guide.md` 搂3 鐨勮璁℃柟妗堛€?|
| **浜у嚭鏂囦欢** | `.github/workflows/pr_ci.yml`锛圥R 绾ц交閲忥級銆乣.github/workflows/daily_ci.yml`锛堟瘡鏃ョ骇鍏ㄩ潰锛?|
| **宸ヤ綔娴佽璁?* | **PR 绾э紙pr_ci.yml锛夛細**<br>```yaml<br>name: PR CI<br>on:<br>  pull_request:<br>    branches: [master]<br>  push:<br>    branches: [master]<br><br>jobs:<br>  verify:<br>    runs-on: [self-hosted, windows, fzm-zenbook]<br>    timeout-minutes: 5<br>    steps:<br>      - uses: actions/checkout@v4<br>      - name: Setup Python<br>        uses: actions/setup-python@v5<br>        with:<br>          python-version: '3.10'<br>      - name: Install Dependencies<br>        run: pip install -e .<br>      - name: Verify Import<br>        run: python -c "from automation_v2 import *; print('Import OK')"<br>      - name: Collect-Only Dry Run<br>        run: .\run_verify_ci.ps1 -CollectOnly<br>        shell: powershell<br>```<br><br>**姣忔棩绾э紙daily_ci.yml锛夛細**<br>```yaml<br>name: Daily Full Regression<br>on:<br>  schedule:<br>    - cron: '0 21 * * *'  # 鍖椾含鏃堕棿 05:00锛圲TC 21:00锛?br>  workflow_dispatch:       # 鎵嬪姩瑙﹀彂<br><br>jobs:<br>  full-regression:<br>    runs-on: [self-hosted, windows, fzm-zenbook]<br>    timeout-minutes: 30<br>    steps:<br>      - uses: actions/checkout@v4<br>      - name: Setup Python<br>        uses: actions/setup-python@v5<br>        with:<br>          python-version: '3.10'<br>      - name: Install Dependencies<br>        run: pip install -e .<br>      - name: Collect-Only<br>        run: .\run_verify_ci.ps1 -CollectOnly<br>        shell: powershell<br>      - name: Full Regression (core + moheng)<br>        run: .\run_verify_ci.ps1 -SkipVerify -XmlReport<br>        shell: powershell<br>      - name: Full Regression (verify suites)<br>        run: .\run_verify_ci.ps1 -SkipCore -SkipMoheng -XmlReport<br>        shell: powershell<br>      - name: Upload Reports<br>        uses: actions/upload-artifact@v4<br>        with:<br>          name: test-reports<br>          path: tests/_junit_*.xml<br>``` |
| **楠屾敹鏍囧噯** | 涓や釜 YAML 鏂囦欢璇硶姝ｇ‘锛坄gh workflow list` 鑳借瘑鍒級锛屾帹閫佸埌 GitHub 鍚?Actions 椤甸潰鍑虹幇瀵瑰簲宸ヤ綔娴?|
| **椋庨櫓** | 浣庯紙閰嶇疆鏂囦欢鍙湪鏈湴棰勫厛缂栧啓娴嬭瘯锛?|

---

### T5.5锛堝彲閫夛級锛歅R 绾?vs 姣忔棩绾?鍒嗘壒绛栫暐

> 鍥?fzm-zenbook 鍙敤鍐呭瓨浠?1.5GB锛屽畬鏁?5 濂椾欢涓茶鍥炲綊鍙兘 OOM銆傝嫢 T3 纭涓嶅彲琛岋紝灏嗘瘡鏃ョ骇鎷嗗垎涓?3 鎵癸細

```yaml
# 姣忔棩绾ф媶鍒嗘柟妗?Batch 1: core 濂椾欢锛垀30 min锛?Batch 2: moheng + verify_001锛垀10 min锛?Batch 3: verify_002 + verify_003锛垀10 min锛?
# 鏃堕棿鎴抽敊寮€ 15 min 闂撮殧锛岄伩鍏嶅苟鍙戣祫婧愮珵浜?```

姝ゅ垎鏀柟妗堜粎鍦?T3 楠岃瘉 OOM 鍚庡惎鐢ㄣ€?
---

### T6锛氳Е鍙?CI 杩愯

| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 鎺ㄩ€佷唬鐮佽Е鍙戦娆?CI |
| **棰勪及鑰楁椂** | 5 min |
| **渚濊禆** | T2锛堜粨搴撳氨缁級+ T3锛圧unner 鍦ㄧ嚎锛? T5锛堝伐浣滄祦鏂囦欢宸插悎骞跺埌 master锛?|
| **鎻忚堪** | 灏嗗伐浣滄祦鏂囦欢鎻愪氦鎺ㄩ€侊紝瑙﹀彂 push 浜嬩欢銆?|
| **鎿嶄綔姝ラ** | 1. `git add .github/workflows/`<br>2. `git commit -m "chore: add CI workflows (PR + daily)"`<br>3. `git push origin master`<br>4. 纭 GitHub Actions 椤甸潰鍑虹幇杩愯璁板綍 |
| **楠屾敹鏍囧噯** | GitHub Actions 椤甸潰鏄剧ず宸ヤ綔娴佸凡瑙﹀彂锛岀姸鎬佷负 "Queued" 鈫?"In progress" |
| **椋庨櫓** | 鑻?Runner 绂荤嚎锛屽伐浣滄祦浼氬崱鍦?Queued 鐘舵€?24h 鍚庤秴鏃?|

---

### T7锛氳瀵熼娆?CI 缁撴灉

| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 鐩戞帶棣栨 CI 鎵ц鐘舵€?|
| **棰勪及鑰楁椂** | 10 min锛堢瓑寰咃級+ 5 min锛堟鏌ユ棩蹇楋級 |
| **渚濊禆** | T6锛圕I 宸茶Е鍙戯級 |
| **鎻忚堪** | 绛夊緟 Runner 鎷夊彇浠诲姟骞舵墽琛岋紝妫€鏌ユ瘡涓楠ょ殑杈撳嚭鏃ュ織銆?|
| **鎿嶄綔姝ラ** | 1. 鎵撳紑 GitHub Actions 杩愯璁板綍<br>2. 閫愭楠ゆ鏌ユ棩蹇楋細<br>   - Checkout: 纭浠ｇ爜宸叉媺鍙?br>   - Setup Python: 纭 Python 3.10 鍙敤<br>   - Install: 纭 pip install 鎴愬姛<br>   - Collect-Only: 纭 123+ 鐢ㄤ緥鍙彂鐜?br>   - Regression: 纭娴嬭瘯鎵ц<br>3. 璁板綍澶辫触姝ラ鐨勮缁嗛敊璇俊鎭?|
| **楠屾敹鏍囧噯** | CI 鍏ㄩ儴閫氳繃 鉁咃紱鑻ュけ璐ワ紝璁板綍澶辫触鍘熷洜杞叆 T8 |
| **椋庨櫓** | 棣栨杩愯棰勬湡鏈夌幆澧冨樊寮傞棶棰橈紙PATH銆佷緷璧栫増鏈€佽矾寰勬潈闄愮瓑锛?|

---

### T8锛氣槄 淇 CI 澶辫触锛堝惊鐜潡锛?
| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 璇婃柇骞朵慨澶?CI 澶辫触 |
| **棰勪及鑰楁椂** | 姣忚疆 10~15 min锛屾渶澶?2 杞?|
| **渚濊禆** | T7锛堝け璐ユ棩蹇楀氨缁級 |
| **鎻忚堪** | 鏍规嵁 T7 鐨勫け璐ユ棩蹇楀垎绫讳慨澶嶃€傚父瑙侀棶棰橈細<br><br>1. **PATH/渚濊禆**锛歊unner 鎵句笉鍒?python/pytest 鈫?淇 `setup-python` action 鎴栨敼鐢ㄧ粷瀵硅矾寰?br>2. **sys.path 閿欒**锛歊unner 宸ヤ綔鐩綍涓嶅悓锛宨mport 璺緞涓嶄竴鑷?鈫?妫€鏌?`pip install -e .`<br>3. **鍐呭瓨涓嶈冻**锛氬畬鏁?5 濂椾欢鈫?OOM 鈫?鍚敤 T5.5 鍒嗘壒鏂规<br>4. **璺緞纭紪鐮?*锛歚ci_run_guide.md` 涓殑璺緞鍦?Runner 鐜涓嬩笉瀛樺湪 鈫?鏀圭敤鐩稿璺緞<br>5. **鏉冮檺闂**锛歊unner 鏈嶅姟璐︽埛鏃犲啓鍏ユ潈闄?鈫?璋冩暣鐩綍鏉冮檺鎴?Runner 鏈嶅姟璐︽埛<br><br>**淇寰幆瑙勫垯**锛堝ⅷ琛″洖娴嬩細璁?搂8.2 閫傜敤锛夛細<br>- 绗?1 杞細鐩存帴淇锛屾彁浜や慨澶?br>- 绗?2 杞細浠嶆湭閫氳繃锛屽姞娉ㄥ叿浣撲慨鏀硅姹?br>- 瓒呰繃 2 杞?鈫?**鍛婅 Owner 浠嬪叆** |
| **淇鍚庢搷浣?* | `git add . && git commit -m "fix: CI failure - <绠€瑕佸師鍥?" && git push origin master`锛屾墜鍔ㄩ噸鏂拌Е鍙?workflow |
| **楠屾敹鏍囧噯** | CI 鍏ㄩ儴缁胯壊 鉁咃紙鎵€鏈夋鏌ラ€氳繃锛?|
| **椋庨櫓** | 鑻?CI 瑙﹀彂鍒嗘敮淇濇姢锛屼慨澶嶆彁浜ゆ湰韬篃闇€瑕?CI 閫氳繃鍚庢墠鑳藉悎骞讹紙姝诲惊鐜級銆傝閬挎柟寮忥細鐩存帴 push 鍒?master锛堣蛋 push trigger锛屼笉缁忚繃 PR gate锛?|

---

### T9锛氬垎鏀繚鎶ょ瓥鐣ラ厤缃?
| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 閰嶇疆 GitHub 鍒嗘敮淇濇姢瑙勫垯 |
| **棰勪及鑰楁椂** | 10 min |
| **渚濊禆** | T8锛圕I 宸查€氳繃锛岃嚦灏戞湁杩囦竴娆＄豢鑹茶繍琛岋級 |
| **鎻忚堪** | 鍦?GitHub 浠撳簱 Settings 鈫?Branches 涓厤缃?master 鍒嗘敮淇濇姢瑙勫垯锛屾弧瓒冲ⅷ钀辫姹?CI 澶辫触闃绘鍚堝苟"銆?|
| **閰嶇疆椤?* | 1. 鉁?Require a pull request before merging锛堝彲閫?鈥?澧ㄨ惐鏈槑纭姹傦紝浣嗗缓璁紑鍚級<br>2. 鉁?Require status checks to pass before merging<br>3. 鉁?鍕鹃€?"PR CI" 宸ヤ綔娴佺殑鐘舵€佹鏌?br>4. 鉁?Require branches to be up to date锛堝彲閫夛級<br>5. 鉁?Include administrators锛堝彲閫夛級<br>6. 鉁?Do not allow bypassing the above settings |
| **楠屾敹鏍囧噯** | 鍒涘缓 PR 鍚庯紝鑻?CI 鏈€氳繃 鈫?鍚堝苟鎸夐挳鐏拌壊涓旀樉绀?"Required status check must pass" |
| **椋庨櫓** | 鑻ュ垎鏀繚鎶よ繃浜庝弗鏍硷紝Owner 淇绱ф€?bug 鏃跺彲鑳借闃诲銆傞渶閰嶇疆绱ф€?bypass 閫氶亾锛堝 admin bypass 淇濇寔寮€鍚級 |

---

### T10锛氶涔﹂€氱煡楠岃瘉

| 灞炴€?| 鍐呭 |
|:----|:-----|
| **浠诲姟鍚?* | 楠岃瘉 CI 缁撴灉椋炰功閫氱煡 |
| **棰勪及鑰楁椂** | 10 min |
| **渚濊禆** | T8锛圕I 杩愯涓級+ T9锛堝彲閫夛紝闈為樆濉烇級 |
| **鎻忚堪** | 楠岃瘉 CI 鎵ц缁撴灉鑳藉惁閫氱煡鍒伴涔︾兢銆傚綋鍓嶆柟妗堟湁涓ょ閫夋嫨锛?|
| **鏂规 A 鈥?GitHub Actions 鍐呯疆閫氱煡锛堟帹鑽愶級** | GitHub 鍘熺敓鏀寔 Jenkins/Slack/椋炰功 webhook銆傝嫢椋炰功缇ゆ敮鎸?incoming webhook锛?br>1. 鍦ㄩ涔︾兢娣诲姞 Webhook 鏈哄櫒浜?br>2. 鍦?GitHub 浠撳簱 Settings 鈫?Webhooks 娣诲姞椋炰功 webhook<br>3. 閫夋嫨浜嬩欢锛欳heck runs, Workflow runs<br>4. 楠岃瘉锛氭墜鍔ㄨЕ鍙?workflow_dispatch 鈫?纭椋炰功缇ゆ敹鍒伴€氱煡<br>**棰勪及鑰楁椂**锛?0 min |
| **鏂规 B 鈥?鏈湴鑴氭湰閫氱煡锛堝閫夛級** | 鑻ラ涔?webhook 涓嶅彲鐢紝鍦ㄥ伐浣滄祦鏈熬娣诲姞 step锛岄€氳繃椋炰功 OpenClaw 宸ュ叿鍙戦€佹秷鎭細<br>1. 鍦ㄥ伐浣滄祦鏈€鍚庝竴姝ヨ皟鐢ㄩ涔?API 鍙戦€佺粨鏋滄憳瑕?br>2. 浣跨敤 OpenClaw 鐨?message 宸ュ叿锛堥渶鍦?Runner 涓婇厤缃?OpenClaw锛?br>**棰勪及鑰楁椂**锛?5 min |
| **楠屾敹鏍囧噯** | CI 鎴愬姛/澶辫触鍚庯紝椋炰功缇よ嚜鍔ㄦ敹鍒版秷鎭紙鎴愬姛鐜?鈮?90%锛?|
| **椋庨櫓** | 椋炰功 webhook 鏉冮檺鍙兘闇€瑕侀涔︾鐞嗗憳閰嶇疆 |

---

## 鏃堕棿绾匡紙鎸変覆琛屼緷璧栨帓鍒楋級

| 搴忓彿 | 浠诲姟鍚?| 棰勪及鑰楁椂 | 渚濊禆 | 骞惰鍙兘鎬?|
|:----:|:-------|:--------:|:----:|:----------:|
| T1 | 浠撳簱杩滅▼閰嶇疆 | 5 min | 鈥?| 鈥?|
| T2 | GitHub 浠撳簱鍒涘缓 | 10 min | T1 | 鈥?|
| T3 | Runner 瀹夎 | 15 min | T2 | 鈥?|
| T4 | Runner 娉ㄥ唽閰嶇疆 | 5 min | T3 | 鈥?|
| T5 | 宸ヤ綔娴佹枃浠剁紪鍐?| 15 min | 鈥?| 猬?涓?T3/T4 骞惰 |
| T6 | 瑙﹀彂 CI 杩愯 | 5 min | T2+T3+T5 | 鈥?|
| T7 | 瑙傚療棣栨 CI 缁撴灉 | 15 min | T6 | 鈥?|
| T8 | 淇 CI 澶辫触锛堝惊鐜級 | 15 min 脳 鈮? 杞?| T7 | 鈥?|
| T9 | 鍒嗘敮淇濇姢閰嶇疆 | 10 min | T8 | 鈥?|
| T10 | 椋炰功閫氱煡楠岃瘉 | 10 min | T8 | 猬?鍙笌 T9 骞惰 |

**鍏抽敭璺緞鎬昏€楁椂**锛歍1(5) + T2(10) + T3(15) + T4(5) + T5(15, 骞惰) + T6(5) + T7(15) + T8(15脳2) + T9(10) = **~95 min**锛堟棤闃诲鎯呭喌锛?
**鍚?T5.5 鍒嗘壒鏂规**锛?15 min

**鍚杞慨澶嶏紙2 杞級**锛?15 min

**鎬讳笂绾挎椂闂翠及璁?*锛?*~2 灏忔椂**锛堢悊鎯筹級鑷?**~4 灏忔椂**锛堝惈鏁呴殰淇鍜屽垎鎵硅皟鏁达級

---

## 楠屾敹鏍囧噯姹囨€?
| # | 楠屾敹椤?| 璐ｄ换鏂?| 鍏宠仈浠诲姟 | Owner 瑕佹眰鏍囨敞 |
|:-:|:-------|:------:|:--------:|:-------------:|
| 1 | `git remote -v` 姝ｇ‘杈撳嚭 origin URL | 澧ㄨ　 | T1 | 鈥?|
| 2 | GitHub 浠撳簱椤甸潰鍙锛宮aster 鍒嗘敮鍐呭瀹屾暣 | 澧ㄨ　 | T2 | 鈥?|
| 3 | GitHub Settings 鈫?Actions 鈫?Runners 鏄剧ず 1 涓豢鑹?Idle Runner | 澧ㄨ　 | T3 | 鈥?|
| 4 | Runner 鏍囩鍒嗙粍姝ｇ‘锛坰elf-hosted, windows锛?| 澧ㄨ　 | T4 | 鈥?|
| 5 | `pr_ci.yml` 鍜?`daily_ci.yml` 璇硶姝ｇ‘锛屽湪 Actions 椤甸潰涓婂彲瑙?| 澧ㄨ　 | T5 | 鈥?|
| **A** | **PR 绾ф祦姘寸嚎锛氭彁浜よЕ鍙戯紝5 鍒嗛挓鍐呭嚭缁撴灉** | 澧ㄨ　 | T6+T7 | Owner瑕佹眰 #1 |
| **B** | **姣忔棩绾ф祦姘寸嚎锛氬畾鏃惰Е鍙戯紝30 鍒嗛挓鍐呰窇瀹?123 涓熀绾挎祴璇?* | 澧ㄨ　 | T6+T7 | Owner瑕佹眰 #2 |
| **C** | **浜哄伐鍒堕€犱竴涓け璐ョ敤渚嬶紝纭鍚堝苟鎸夐挳琚鐢?*锛堝疄闄呴獙璇侊紝涓嶈兘鍙湅閰嶇疆鏂囦欢锛?| 澧ㄨ　 | T8+T9 | Owner瑕佹眰 #3 鈿狅笍 |
| 6 | 椋炰功缇ゆ敹鍒?CI 鎵ц缁撴灉閫氱煡 | 澧ㄨ　 | T10 | 鈥?|
| 7 | **澧ㄨ惐澶嶆牳**锛氫互涓婂叏閮ㄩ棴鍚?| 澧ㄨ惐 | 鈥?| 鈥?|

**A/B 璇存槑**锛?- A 鍜?B 閫氳繃 T6+T7 涓€娆℃€ч獙璇侊紙PR 绾цЕ鍙戠湅 5min 闄愭椂锛屾瘡鏃ョ骇楠岃瘉鎵嬪姩 trigger workflow_dispatch 鐪嬫槸鍚?30min 瀹屾垚 123 涓熀绾匡級
- 鑻ュ唴瀛樹笉瓒抽渶鍚敤 T5.5 鍒嗘壒鏂规锛屾瘡鏃ョ骇鎬昏€楁椂鏀惧鍒板垎鎵规墽琛岀殑鏃堕棿绐楀彛

**C 璇存槑**锛?- 蹇呴』瀹為檯鍒堕€犲け璐ワ紝涓嶈兘鍙湅 CI 閰嶇疆瀛樺湪
- 鎿嶄綔锛氭晠鎰忓湪娴嬭瘯涓彃鍏ヤ竴涓?`assert False` 鈫?鎻愪氦 PR 鈫?瑙傚療鍚堝苟鎸夐挳鐘舵€?- 楠岃瘉閫氳繃鍚庣珛鍗虫挙鍥炶澶辫触鐢ㄤ緥

---

## 鍥為€€鏂规

鑻ュ洜鐜/鏉冮檺/璧勬簮绾︽潫瀵艰嚧 CI 涓婄嚎鍙楅樆锛屾寜浠ヤ笅浼樺厛绾у洖閫€锛?
| 浼樺厛绾?| 鏂规 | 閫傜敤鍦烘櫙 | 渚濊禆 |
|:------:|:-----|:---------|:----:|
| 1锔忊儯 | 鑷墭绠?Runner锛堟湰鍦版満锛?| GitHub 鍙闂紝鏈湴鏈烘湁璧勬簮 | GitHub 璐﹀彿 |
| 2锔忊儯 | 杩佽嚦浣庨厤 Runner锛堝彟涓€鍙扮┖闂叉満锛?| 鏈満 OOM 鏃犳硶淇 | 澶囩敤鏈哄櫒 |
| 3锔忊儯 | 鑷墭绠?Runner 鍒?3 鎵规墽琛?| 鍐呭瓨涓嶈冻浣嗗彲鍒嗘壒 | 鏃犻澶栦緷璧?|
| 4锔忊儯 | 鏈湴 CRON + 椋炰功閫氱煡 | GitHub Actions 涓嶅彲鐢?| 浠呴渶鏈湴 | 
| 5锔忊儯 | 绾墜鍔ㄥ洖褰?| 浠ヤ笂鍧囦笉鍙 | 鈥?|

---

## 寮曠敤鏂囦欢

- `docs/07_research/plans/verify_next_steps_20260601.md` 鈥?椤圭洰鎬绘帓鏈燂紙CI 涓婄嚎涓?Week 2 P0锛?- `docs/07_research/plans/ci_run_guide.md` 鈥?CI 杩愯璇︾粏鎸囧紩锛堝寘鎷垎灞?CI 璁捐銆佹晠闅滄帓鏌?Q&A锛?- `src/automation_v2/` 鈥?鑷姩鍖栨ā鍧楋紝鍖呭惈娴嬭瘯杩愯鍣?- `tests/run_verify_ci.ps1` 鈥?CI 鏈湴杩愯鑴氭湰锛堝綋鍓嶅彲鐩存帴杩愯锛?- `tests/run_verify_ci.bat` 鈥?CI 鎵瑰鐞嗗叆鍙ｏ紙涓ゆ娴佺▼锛氭敹闆?鈫?鎵ц锛?
