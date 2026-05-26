# KnowledgeBridge 鍓嶇鏂规璁捐

> 浣滆€咃細澧ㄨ　锛圡oHeng锛?> 浠诲姟ID锛歚r2_kb_frontend`
> 鍒涘缓鏃堕棿锛?026-05-17 12:30 +08:00
> 淇鏃堕棿锛?026-05-17 12:58 +08:00锛圫tep6 璇勫鎵撳洖淇锛?> 鐗堟湰锛歷2.0
> 鐘舵€侊細淇绋?
---

## 鐩綍

0. 璁捐鎬昏
1. 鏋舵瀯鍏ㄦ櫙锛?灞傦級
2. KnowledgeEntry v2 鏍囧噯鍗忚 鈽呪槄鈽?3. KnowledgeNormalizer 缁勪欢璁捐
4. Bitable Schema 璁捐
5. BitableSync 鍚屾鍣ㄨ璁?6. Bitable 瀛楁婕旇繘锛坰chema_version锛?7. 鏁版嵁娴佸叏鏅?8. 鍒嗗眰鎺ㄨ繘绛栫暐锛? Phase锛?9. 宸ヤ綔閲忚瘎浼?10. 椋庨櫓涓庡喅绛?11. 涓庣幇鏈夌郴缁熺殑鍏煎鎬?12. 闄勫綍

---

## 0. 璁捐鎬昏

### 0.1 褰撳墠鐘舵€?
```
MethodBacktestRunner 鈫?KnowledgeBridge.harvest() 鈫?knowledge_entries锛圝SON 鏂囦欢瀛樺偍锛?                                                     鈫?Consumers: 鏃狅紙涓嶅彲娴忚銆佷笉鍙绱級
```

**鐜扮姸锛?* 鐭ヨ瘑鏀跺壊鍚庝粎浠?JSON 鏂囦欢瀛樺偍锛屾棤缁撴瀯鍖栨秷璐圭銆備笉瀛樺湪鐙珛鐨?SQLite knowledge.db 鏂囦欢锛?KnowledgeBridge 鏄€氳繃 import 鍦?engine 鍐呴儴浣跨敤鐨勬ā鍧楋紝闈炵嫭绔嬫枃浠惰矾寰勩€侭itable 鐭ヨ瘑灞曠ず銆?鐭ヨ瘑鏍囧噯鍖栫粍浠跺潎闇€浠庨浂鍒涘缓銆?
**鏍稿績闂锛?* 鐭ヨ瘑鍙繘涓嶅嚭锛屾病鏈夋秷璐圭銆?
### 0.2 鐩爣

璁╃煡璇嗗彲娴忚銆佸彲妫€绱€佸彲娑堣垂銆傚叿浣撹€岃█锛?
| 鑳藉姏 | Phase 鍙揪 | 璇存槑 |
|:-----|:-----------|:-----|
| 椋炰功鐭ヨ瘑鍗＄墖灞曠ず | Phase 1 | Bitable 浣滀负鏈€灏忓彲鐢ㄧ晫闈?|
| 鏍囩/杩囨护/鎼滅储 | Phase 2 | 澶氱淮搴︽绱?|
| 鍙傛暟绋冲畾鎬у垎鏋愩€佺瓥鐣ヨ仛绫讳笌瑙勫緥鍙戠幇 | Phase 3 | Knowledge Analysis Layer |
| 鐭ヨ瘑琛板噺涓庡彲淇″害 | Phase 1 鍩虹 | quality_score 杩借釜 |
| 鍥炴祴鍙傛暟婧簮 | Phase 1 | source_run_id 鏈哄埗 |

### 0.3 璁捐鍘熷垯

| 鍘熷垯 | 璇存槑 |
|:-----|:------|
| **浠庨浂鍒涘缓** | KnowledgeEntry v2 鍩虹被銆並nowledgeNormalizer銆丅itableSync 鍧囦粠闆舵瀯寤猴紝涓嶄緷璧栫幇鏈夋枃浠剁粨鏋?|
| **Bitable 浣滀负娑堣垂鐣岄潰** | 涓嶆柊寤?Web UI锛屽€熼涔︾敓鎬侀檷浣庡紑鍙戞垚鏈?|
| **鏉冮檺浼樺厛纭** | Bitable 鎿嶄綔鍓嶉渶纭繚椋炰功 App 宸叉坊鍔?bitable:bitable 鏉冮檺 |
| **闃舵瀹炴柦** | Phase 1 鍏堝仛缁撴瀯鍖栫煡璇?+ Bitable 鍙锛屼笉鎬?AI |
| **骞傜瓑鍚屾** | 閲嶅璋冪敤涓嶄骇鐢熼噸澶嶈褰?|
| **鍙拷婧?* | 姣忔潯鐭ヨ瘑鏉＄洰鍙拷婧埌鍘熷鍥炴祴 run_id |

---

## 1. 鏋舵瀯鍏ㄦ櫙锛?灞傦級

```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Layer 4: Knowledge Analysis Layer      Phase 3                      鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹? 鈹? 鍙傛暟绋冲畾鎬у垎鏋愶細鍝簺鍙傛暟閰嶇疆鏈€绋冲畾锛?                        鈹?  鈹?鈹? 鈹? 绛栫暐鑱氱被锛氬摢浜涚瓥鐣ュ睘浜庡悓绫伙紵锛堝熀浜庣粺璁¤窛绂伙級                 鈹?  鈹?鈹? 鈹? 妯℃澘鍖栨憳瑕侊細鍩轰簬缁熻瑙勫垯鐨勫浐瀹氭ā鏉胯緭鍑?                      鈹?  鈹?鈹? 鈹? 瑙勫緥鍙戠幇锛氫綆娉㈠姩鏃?MA 绫昏〃鐜版洿濂?                            鈹?  鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                    鈻?                                    鈹?娑堣垂
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Layer 3: 灞曠ず灞?                    Phase 2 鈫?Phase 3               鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹?鈹? 鈹? 椋炰功鐭ヨ瘑鍗＄墖锛圔itable锛?  鈹? 鈹? 鍒嗘瀽闈㈡澘锛圥hase 3锛?         鈹?   鈹?鈹? 鈹? 鏍囩杩囨护 / 鎼滅储          鈹? 鈹? 鍙傛暟绋冲畾鎬?/ 绛栫暐鑱氱被         鈹?   鈹?鈹? 鈹? 澶氱淮搴︽帓搴?/ 瀵规瘮        鈹? 鈹? 妯℃澘鍖栨憳瑕佸睍绀?              鈹?   鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                    鈻?                                    鈹?鍚屾
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Layer 2: 鍚屾灞?                    Phase 1                          鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹? 鈹? BitableSync 鍚屾鍣?                                           鈹?  鈹?鈹? 鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?  鈹?鈹? 鈹? 鈹?澧為噺鍚屾    鈹?鈹?閲嶈瘯闃熷垪   鈹?鈹?鍘婚噸寮曟搸  鈹?鈹俿chema_v    鈹?  鈹?  鈹?鈹? 鈹? 鈹?(append)   鈹?鈹?(鎸囨暟閫€閬? 鈹?鈹?task_id+  鈹?鈹俥rsion杩借釜  鈹?  鈹?  鈹?鈹? 鈹? 鈹?           鈹?鈹?           鈹?鈹俶ethod+   鈹?鈹?           鈹?  鈹?  鈹?鈹? 鈹? 鈹?           鈹?鈹?           鈹?鈹俿ymbol)   鈹?鈹?           鈹?  鈹?  鈹?鈹? 鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?  鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                    鈻?                                    鈹?鏍囧噯鍖?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Layer 1.5: 鏁版嵁鏍囧噯鍖栧眰             Phase 1                          鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹? 鈹? KnowledgeNormalizer 缁勪欢                                    鈹?  鈹?鈹? 鈹? 杈撳叆锛欿nowledgeEntry v1锛堝師濮嬶級                               鈹?  鈹?鈹? 鈹? 杈撳嚭锛欿nowledgeEntry v2锛堟爣鍑嗗寲锛?                             鈹?  鈹?鈹? 鈹? 鑱岃矗锛氬紓鏋勫弬鏁版爣鍑嗗寲銆佸競鍦虹姸鎬佹爣璁般€佽川閲忚瘎鍒?                     鈹?  鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?  鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                    鈻?                                    鈹?鏀跺壊
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Layer 1: 鏁版嵁婧愬眰锛堜粠闆跺垱寤猴級                                         鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                              鈹?鈹? 鈹? KnowledgeEntry v2 鍩虹被 + Normalizer 杈撳叆灞?                       鈹?鈹? 鈹? 锛堜粠闆跺垱寤?dataclass 涓庢爣鍑嗗寲缁勪欢锛?                                鈹?鈹? 鈹? 浣滆€咃細澧ㄨ　锛圥hase 1a锛?           鈹?                              鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                              鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

### 鏁版嵁娴?
```
BacktestResult
    鈫?KnowledgeBridge.harvest()
    鈫?raw knowledge_entries锛圝SON 鏂囦欢锛?    鈫?KnowledgeNormalizer.normalize()    鈫?鏂板锛圠ayer 1.5锛?    鈫?KnowledgeEntry v2锛堟爣鍑嗗寲锛?         鈫?鏂板鍗忚锛堜粠闆跺垱寤猴級
    鈫?BitableSync.sync()                 鈫?鏂板锛圠ayer 2锛?    鈫?Feishu Bitable                      鈫?鏂板锛圠ayer 3 灞曠ず锛?    鈫?Knowledge Analysis Layer锛圥hase 3锛? 鈫?Phase 3
```

---

## 2. KnowledgeEntry v2 鏍囧噯鍗忚 鈽呪槄鈽?
### 2.1 v1 鈫?v2 鍗忚鍗囩骇

KnowledgeEntry v2 鍗忚浠庨浂鍒涘缓锛屽寘鍚煡璇嗘秷璐圭鎵€闇€鐨勫畬鏁村瓧娈甸泦銆倂2 瀛楁娓呭崟濡備笅锛?
| 鍙樻洿 | 瀛楁 | 浣嶇疆 | 璇存槑 |
|:-----|:-----|:-----|:------|
| 鉁?鏂板 | `regime` | 椤跺眰瀛楁 | 甯傚満鐘舵€佹爣绛?|
| 鉁?鏂板 | `timeframe` | 椤跺眰瀛楁 | 鏃堕棿妗嗘灦 |
| 鉁?鏂板 | `tags` | 椤跺眰瀛楁 | 澶氱淮鏍囩锛堟绱㈢敤锛?|
| 鉁?鏂板 | `source_run_id` | 椤跺眰瀛楁 | 杩芥函鍘熷鍥炴祴 |
| 鉁?鏂板 | `quality_score` | 椤跺眰瀛楁 | 鑷姩璇勫垎 |
| 鉁?鏂板 | `total_return` | 椤跺眰瀛楁 | 鎬绘敹鐩婄巼锛堢嫭绔嬪垪锛?|
| 鉁?鏂板 | `sharpe` | 椤跺眰瀛楁 | 澶忔櫘姣旂巼锛堢嫭绔嬪垪锛?|
| 鉁?鏂板 | `max_drawdown` | 椤跺眰瀛楁 | 鏈€澶у洖鎾ょ巼锛堢嫭绔嬪垪锛?|
| 鉁?鏂板 | `win_rate` | 椤跺眰瀛楁 | 鑳滅巼锛堢嫭绔嬪垪锛?|
| 鉁?鏂板 | `normalized_params` | 椤跺眰瀛楁 | 鏍囧噯鍖栧弬鏁板瓧鍏?|
| 鈿狅笍 淇濈暀 | `insight_summary` | 椤跺眰瀛楁 | 鏀逛负缁撴瀯鍖栨枃鏈紙闈?JSON blob锛墊
| 鈿狅笍 淇濈暀 | `confidence` | 椤跺眰瀛楁 | 鏀逛负 `quality_score` 鏇夸唬鍏ュ彛璇勫垎 |
| 鈿狅笍 淇濈暀 | `metadata` | 椤跺眰瀛楁 | 鎵╁睍瀛樺偍锛宒istribution 绛夊鏉傚唴瀹规斁杩欓噷 |

### 2.2 KnowledgeEntry v2 瀹屾暣瀹氫箟

```python
# 鈹€鈹€鈹€ src/backtest/engine/knowledge_bridge_v2.py (鎴栧師鍦板崌绾? 鈹€鈹€鈹€

@dataclass
class KnowledgeEntryV2:
    """鐭ヨ瘑鏉＄洰 v2 鈥?鏀拺 Bitable 灞曠ず涓庣煡璇嗘秷璐广€?
    涓?v1 鐨勪富瑕佸尯鍒細
    - 椤跺眰瀛楁鍖呭惈鏍稿績鎸囨爣锛坱otal_return, sharpe 绛夌嫭绔嬪垪锛?    - 鏂板 regime / timeframe / tags / source_run_id / quality_score
    - params 淇濈暀鍘熷鍙傛暟蹇収
    - normalized_params 鎻愪緵鏍囧噯鍖栧悗鐨勭瓥鐣ラ€氱敤鍙傛暟
    - metadata 瀛樻斁澶嶆潅缁撴瀯锛坉istribution, equity_curve 绛?JSON锛?    """

    # 鈹€鈹€鈹€ 鏍囪瘑瀛楁锛坴1 淇濈暀锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    task_id: str                        # 鍥炴祴/浠诲姟鍞竴鏍囪瘑 ID
    method_name: str                    # 鎵ц鐨勬柟娉曞悕
    symbol: str                         # 浜ゆ槗鏍囩殑浠ｇ爜

    # 鈹€鈹€鈹€ 鍙傛暟瀛楁锛坴1 缁ф壙 + v2 鏂板锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    params: Dict[str, Any]              # 鍘熷鍙傛暟蹇収锛坴1 缁ф壙锛?    normalized_params: Dict[str, Any]   # 鈽?鏍囧噯鍖栧弬鏁板瓧鍏革紙v2 鏂板锛?    """灏嗗紓鏋勭瓥鐣ュ弬鏁版爣鍑嗗寲涓虹粺涓€瀛楁鍚嶃€?    渚嬪锛歵rend 鐨?ma_period 鈫?normalized_params["period"]
          grid 鐨?grid_spacing 鈫?normalized_params["spacing"]
    鐢?KnowledgeNormalizer 缁勪欢濉厖銆?    """

    # 鈹€鈹€鈹€ 甯傚満涓婁笅鏂囷紙v2 鏂板锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    regime: str = "unknown"             # 鈽?甯傚満鐘舵€佹爣绛?    """甯傚満鐘舵€侊細bull / bear / sideways / volatile / unknown"""
    timeframe: str = "1d"               # 鈽?鏃堕棿妗嗘灦
    """鏁版嵁棰戠巼锛?d / 4h / 1h / 15m / 5m / 1m"""

    # 鈹€鈹€鈹€ 妫€绱㈡爣绛撅紙v2 鏂板锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    tags: List[str] = field(default_factory=list)
    """澶氱淮鏍囩锛岀敤浜?Bitable 妫€绱㈣繃婊ゃ€?    棰勮鏍囩浣撶郴锛?    - 绛栫暐绫诲瀷: trend, mean_reversion, grid, momentum, breakout
    - 鎶€鏈洜瀛? ma, macd, rsi, vwap, bollinger, volume
    - 椋庢牸鏍囩: long_only, short_term, swing, high_freq
    """

    # 鈹€鈹€鈹€ 鍐呭瀛楁锛坴1 鍗囩骇锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    insight_summary: str = ""
    """缁撴瀯鍖栨憳瑕佹枃鏈€?    v1 浣跨敤鐨勬槸鏂囨湰鎷兼帴锛泇2 寤鸿淇濇寔姝ゅ瓧娈碉紝浣嗘牳蹇冩寚鏍囩嫭绔嬩负椤跺眰瀛楁銆?    姝ゅ瓧娈靛瓨鏀句汉绫诲彲璇荤殑鎬荤粨 / 鐭ヨ瘑缁撹銆?    """
    data_range: str = ""                # 鏁版嵁瑕嗙洊鑼冨洿锛坴1 淇濈暀锛?    data_frequency: str = "daily"       # 鏁版嵁棰戠巼锛坴1 淇濈暀锛?    completed_time: str = ""            # 鎵ц瀹屾垚鏃堕棿锛坴1 淇濈暀锛?
    # 鈹€鈹€鈹€ 鏍稿績鎸囨爣锛坴2 鐙珛椤跺眰瀛楁锛?鈽?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    total_return: float = float("nan")  # 鎬绘敹鐩婄巼
    sharpe: float = float("nan")        # 澶忔櫘姣旂巼
    max_drawdown: float = float("nan")  # 鏈€澶у洖鎾ょ巼
    win_rate: float = float("nan")      # 鑳滅巼

    #### 涓轰粈涔堜笉瀛?JSON blob锛?    # 1. Bitable 鏃犳硶瀵?JSON blob 鍐呯殑瀛楁鍋氭帓搴忋€佽繃婊ゃ€佽绠?    # 2. 鏌ヨ "sharpe > 1.0 鐨勬墍鏈夎秼鍔跨瓥鐣? 鍙互鐩存帴杩囨护鐙珛鍒?    # 3. 椋炰功 Bitable 澶氳〃鍗曞叕寮忓彲寮曠敤鐙珛鍒楀仛琛嶇敓璁＄畻
    # 4. 澶嶆潅鍐呭锛坉istribution, equity_curve锛変粛鏀?metadata JSON

    # 鈹€鈹€鈹€ 璐ㄩ噺淇″彿锛坴2 鍗囩骇锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    quality_score: float = 0.5          # 鈽?鑷姩璇勫垎 [0.0, 1.0]
    """鐢?KnowledgeBridge 缁煎悎璁＄畻鐨勮嚜鍔ㄨ瘎鍒嗐€?    璇勫垎鍥犲瓙锛?    - 鏍锋湰鏁帮紙n_bars 瓒婂瓒婇珮锛?    - 鍥炴祴闀垮害锛堣鐩栧懆鏈熻秺闀胯秺楂橈級
    - 绋冲畾鎬э紙杩炵画澶氭湡鍚屼竴绛栫暐涓嬬浉浼肩粨鏋滐級
    - 缁熻鏄捐憲鎬э紙significance_level锛?    鍙栦唬鏃х殑 confidence 瀛楁锛屼絾淇濈暀 confidence 鍋氬悗缁汉宸ュ鏍哥敤銆?    """

    confidence: float = 0.5             # 淇濈暀锛氱疆淇″害锛堜笌 v1 鐩稿悓閫昏緫锛?    source_run_id: str = ""             # 鈽?杩芥函鍘熷鍥炴祴 run_id
    """鏍煎紡锛歳un_{strategy}_{symbol}_{config_key}_{tag}_{YYYYMMDD_HHMMSS}
    涓?knowledge.db 鐨?backtest_runs.run_id 涓€鑷淬€?    """

    source_file: str = ""               # 鏉ユ簮鏂囦欢璺緞锛坴1 淇濈暀锛?    review_status: str = "pending"      # pending / reviewed / rejected锛坴1 淇濈暀锛?
    # 鈹€鈹€鈹€ 鎵╁睍瀛樺偍锛坴1 淇濈暀锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    metadata: Dict[str, Any] = field(default_factory=dict)
    """鎵╁睍鍏冩暟鎹€傚瓨鏀惧鏉傜粨鏋勶細
    绀轰緥锛?    {
        "distribution": {"p10": -2.1, "p50": 1.8, "p90": 5.2},
        "equity_curve": [{"date": "20250101", "value": 1.0}, ...],
        "monthly_returns": {...},
        "extra_metrics": {"profit_factor": 1.5, "calmar": 1.2},
        "custom_tags": ["momentum", "volume_confirmation"],
    }
    """

    # 鈹€鈹€鈹€ 鏃堕棿鎴筹紙v1 淇濈暀锛?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"))
```

### 2.3 瀛楁瀹屾暣鎬ф牎楠?
#### 2.3.1 蹇呭～瀛楁

| 瀛楁 | 蹇呭～鍘熷洜 | 缂虹渷澶勭悊 |
|:-----|:---------|:---------|
| task_id | 鍞竴鏍囪瘑 | raise ValueError |
| method_name | 鐭ヨ瘑褰掔被 | raise ValueError |
| symbol | 鏍囩殑缁戝畾 | raise ValueError |
| params | 鍙傛暟杩芥函 | 鍏佽绌?dict |
| completed_time | 鏃舵晥鎬?| 鍙栧綋鍓嶆椂闂?|
| total_return | 鏍稿績鎸囨爣 | 鍏佽 NaN锛堣〃绀轰笉鍙敤锛?|
| sharpe | 鏍稿績鎸囨爣 | 鍏佽 NaN |
| max_drawdown | 鏍稿績鎸囨爣 | 鍏佽 NaN |
| win_rate | 鏍稿績鎸囨爣 | 鍏佽 NaN |

#### 2.3.2 蹇呭～鏍￠獙浠ｇ爜娈?
```python
REQUIRED_FIELDS = ["task_id", "method_name", "symbol"]

def validate_entry(entry: KnowledgeEntryV2) -> bool:
    for field_name in REQUIRED_FIELDS:
        value = getattr(entry, field_name, None)
        if not value or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(
                f"KnowledgeEntryV2 validation failed: {field_name} is required"
            )
    return True
```

### 2.4 JSON 搴忓垪鍖栨牸寮忥紙绀轰緥锛?
```json
{
  "task_id": "eval_backtest_ma_cross_v4",
  "method_name": "ma_cross",
  "symbol": "601857.SH",
  "params": {"fast": 5, "slow": 20},
  "normalized_params": {"fast_period": 5, "slow_period": 20, "type": "trend_following"},
  "regime": "bull",
  "timeframe": "1d",
  "tags": ["trend", "ma", "long_only"],
  "insight_summary": "MA5/20閲戝弶淇″彿鍦ㄤ笂鍗囪秼鍔夸腑鑳滅巼杈冮珮銆傛€绘敹鐩婄巼+12.5%锛屽鏅?.8銆?,
  "data_range": "2025-01-01~2025-12-31",
  "data_frequency": "daily",
  "completed_time": "2026-05-17T09:00:00+08:00",
  "total_return": 12.5,
  "sharpe": 1.8,
  "max_drawdown": -5.2,
  "win_rate": 65.0,
  "quality_score": 0.72,
  "confidence": 0.7,
  "source_run_id": "run_trend_601857_SH_cfg_v4_20260517_090000",
  "source_file": "reports/morning/20260517/structured_analysis_xxx.json",
  "review_status": "pending",
  "metadata": {
    "distribution": {"p10": -1.5, "p50": 2.1, "p90": 8.3},
    "extra_metrics": {"profit_factor": 2.1, "calmar": 1.5, "sortino": 2.0},
    "signal_density": 0.15
  },
  "created_at": "2026-05-17T12:30:00+08:00",
  "updated_at": "2026-05-17T12:30:00+08:00"
}
```

### 2.5 KnowledgeEntry v2 鈫?Bitable 瀛楁鏄犲皠

| KnowledgeEntry v2 瀛楁 | Bitable 鍒楀悕 | Bitable 绫诲瀷 | 澶囨敞 |
|:----------------------|:------------|:-------------|:------|
| task_id | task_id | Text | 涓婚敭鍘婚噸渚濇嵁涔嬩竴 |
| method_name | method_name | Text | 绛栫暐鍚?|
| symbol | symbol | Text | 鏍囩殑浠ｇ爜 |
| regime | regime | SingleSelect | bull/bear/sideways/volatile |
| timeframe | timeframe | SingleSelect | 1d/4h/1h/15m |
| tags | tags | MultiSelect | 澶氱淮鏍囩 |
| insight_summary | insight_summary | Text | 缁撴瀯鍖栨憳瑕?|
| total_return | total_return | Number | 鎬绘敹鐩婄巼 |
| sharpe | sharpe | Number | 澶忔櫘姣旂巼 |
| max_drawdown | max_drawdown | Number | 鏈€澶у洖鎾?|
| win_rate | win_rate | Number | 鑳滅巼 |
| quality_score | quality_score | Number | 鐭ヨ瘑璐ㄩ噺璇勫垎 |
| confidence | confidence | Number | 缃俊搴?|
| source_run_id | source_run_id | Text | 杩芥函 run_id |
| review_status | review_status | SingleSelect | pending/reviewed/rejected |
| completed_time | completed_time | DateTime | 瀹屾垚鏃堕棿 |
| created_at | created_at | DateTime | 鍒涘缓鏃堕棿 |
| metadata | metadata | Text | JSON 瀛楃涓诧紙椋炰功涓嶆敮鎸?Dict锛墊
| normalized_params | normalized_params | Text | JSON 瀛楃涓?|
| params | params | Text | JSON 瀛楃涓?|

### 2.6 鍘婚噸閿畾涔?
鍘婚噸浣跨敤缁勫悎閿細`(task_id, method_name, symbol)`

- 鍚屼竴 task_id + 鍚屼竴鏂规硶 + 鍚屼竴鏍囩殑 鈫?鍚屼竴鏉＄煡璇?- 鑻ラ噸澶嶏紝浣跨敤 **merge** 绛栫暐锛堟洿鏂板瓧娈?+ 鎵╁睍 metadata锛?- 姘镐笉 append 閲嶅璁板綍

### 2.7 schema_version 杩借釜

> 鈿狅笍 **渚濊禆鏉′欢锛?* 椋炰功 App 闇€娣诲姞 `bitable:bitable` 鏉冮檺骞堕噸鏂板彂甯冿紝鍚﹀垯 Bitable 鐩稿叧 API 璋冪敤灏嗗け璐ャ€?
姣忔潯 Bitable 璁板綍鍖呭惈涓€涓笉鍙瀛楁 `_schema_version`锛?
```
_schema_version: Text, 榛樿 "v1.0"
```

婕旇繘璁板綍锛?
| 鐗堟湰 | 鍙樻洿鏃堕棿 | 鍙樻洿鍐呭 |
|:-----|:---------|:---------|
| v1.0 | Phase 1 鍒濆 | 鍏ㄩ儴 v2 鍗忚瀛楁 |
| v1.1 | 鏈潵 | 鏂板 XXX 瀛楁 |
| v2.0 | Phase 3 | Knowledge Analysis Layer 闄勫姞瀛楁 |

`schema_version` 璁板綍鍦?Bitable 鍏冧俊鎭腑锛圔itable 琛ㄥご鐨?description 瀛楁锛夛細
```
schema_version=v1.0; created=2026-05-17; author=moheng
```

---

## 3. KnowledgeNormalizer 缁勪欢璁捐

### 3.1 璁捐鍔ㄦ満

涓嶅悓绛栫暐鐨勫弬鏁扮粨鏋勫ぉ鐒跺紓鏋勶細

| 绛栫暐 | 鍘熷鍙傛暟 | 缁撴瀯宸紓 |
|:-----|:---------|:---------|
| MA Cross (`trend`) | `{fast: 5, slow: 20}` | 涓ゅ懆鏈熷弬鏁?|
| Grid (`grid`) | `{grid_levels: 10, grid_spacing: 0.5}` | 缃戞牸闂磋窛銆佸眰鏁?|
| Bollinger (`bollinger`) | `{period: 20, std_dev: 2.0}` | 鍛ㄦ湡+鏍囧噯宸?|
| RSI (`rsi`) | `{period: 14, overbought: 70, oversold: 30}` | 鍗曞懆鏈?闃堝€?|
| Reversal | `{lookback: 10, cooling_period: 5}` | 鍥炵湅+鍐峰嵈 |

Bitable 鏃犳硶瀵瑰紓鏋勫瓧娈靛仛缁熶竴妫€绱€傝В鍐虫柟妗堬細**KnowledgeNormalizer 灏嗗紓鏋勫弬鏁版槧灏勫埌缁熶竴鍛藉悕绌洪棿銆?*

### 3.2 鎺ュ彛瀹氫箟

```python
class KnowledgeNormalizer:
    """鐭ヨ瘑鏍囧噯鍖栧櫒 鈥?灏嗗紓鏋勭瓥鐣ュ弬鏁版槧灏勫埌缁熶竴鍛藉悕绌洪棿銆?
    鏍稿績鑱岃矗锛?    1. 鍙傛暟鏍囧噯鍖栵細涓嶅悓绛栫暐鐨勫悓璇箟鍙傛暟缁熶竴鍛藉悕
    2. 甯傚満鐘舵€佹爣璁帮細鑷姩鍒ゅ畾 regime锛堥渶澶栭儴鏁版嵁杈撳叆锛?    3. 澶氱淮鏍囩鐢熸垚锛氬熀浜?params + method_name 鑷姩鎵撴爣绛?    4. quality_score 鍗囩骇璁＄畻锛氫繚鐣欏師鏈夐€昏緫锛屽鍔犵ǔ瀹氭€у洜瀛?    """

    def __init__(self, market_data_provider: Optional[Callable] = None):
        """鍒濆鍖栥€?
        Args:
            market_data_provider: 鍙€夌殑甯傚満鏁版嵁鎺ュ彛锛堢敤浜庤嚜鍔ㄥ垽瀹?regime锛夈€?              绛惧悕锛歞ef get_market_regime(symbol: str, date: str) -> str
        """
        self._market_provider = market_data_provider

    def normalize(
        self,
        entry_v1: KnowledgeEntry,
        extra: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeEntryV2:
        """灏?v1 KnowledgeEntry 鍗囩骇涓?v2 鏍囧噯鍖栨潯鐩€?
        Args:
            entry_v1: KnowledgeEntry v1 瀹炰緥銆?            extra: 棰濆杈撳叆锛堝彲閫夛級锛屾敮鎸侊細
              - regime: str锛堟墜鍔ㄦ寚瀹氬競鍦虹姸鎬侊級
              - timeframe: str锛堟墜鍔ㄦ寚瀹氭椂闂存鏋讹級
              - tags: List[str]锛堟墜鍔ㄦ寚瀹氭爣绛撅級
              - core_metrics: Dict锛堟墜鍔ㄦ寚瀹氭牳蹇冩寚鏍囧€硷級

        Returns:
            KnowledgeEntryV2: 鏍囧噯鍖栧悗鐨?v2 鏉＄洰銆?        """
        v2 = KnowledgeEntryV2(
            task_id=entry_v1.task_id,
            method_name=entry_v1.method_name,
            symbol=entry_v1.symbol,
            params=entry_v1.params,
            normalized_params=self._normalize_params(entry_v1.method_name, entry_v1.params),
            regime=self._determine_regime(entry_v1, extra),
            timeframe=extra.get("timeframe") if extra else self._infer_timeframe(entry_v1),
            tags=self._generate_tags(entry_v1, extra),
            insight_summary=entry_v1.insight_summary,
            data_range=entry_v1.data_range,
            data_frequency=entry_v1.data_frequency,
            completed_time=entry_v1.completed_time,
            total_return=self._extract_metric("total_return", entry_v1, extra),
            sharpe=self._extract_metric("sharpe", entry_v1, extra),
            max_drawdown=self._extract_metric("max_drawdown", entry_v1, extra),
            win_rate=self._extract_metric("win_rate", entry_v1, extra),
            quality_score=self._compute_quality_score(entry_v1),
            confidence=entry_v1.confidence,
            source_run_id=extra.get("source_run_id") if extra else "",
            source_file=entry_v1.source_file,
            review_status=entry_v1.review_status,
            metadata=entry_v1.metadata,
            created_at=entry_v1.created_at,
            updated_at=entry_v1.updated_at,
        )
        return v2
```

### 3.3 鍙傛暟鏍囧噯鍖栨槧灏勮〃

#### 3.3.1 绛栫暐绫诲瀷妫€娴?
鏍规嵁 `method_name` 鑷姩妫€娴嬬瓥鐣ョ被鍨嬶紝浠庤€岄€夋嫨姝ｇ‘鐨勬槧灏勮鍒欙細

```python
STRATEGY_TYPE_MAP = {
    "ma_cross": "trend_following",
    "macd": "trend_following",
    "bollinger": "trend_following",
    "grid": "grid",
    "rsi": "mean_reversion",
    "kdj": "mean_reversion",
    "bias": "mean_reversion",
    "reversal": "mean_reversion",
    "vwap": "volume_based",
    "obv": "volume_based",
}
```

#### 3.3.2 缁熶竴鍛藉悕绌洪棿

```python
PARAM_NORMALIZATION_RULES = {
    "trend_following": {
        "period": lambda p: (p.get("fast", 0) + p.get("slow", 0)) // 2,
        "fast_period": lambda p: p.get("fast", None),
        "slow_period": lambda p: p.get("slow", None),
        "std_dev": lambda p: p.get("std_dev", p.get("std", None)),
        "entry_threshold": lambda p: p.get("threshold", None),
    },
    "mean_reversion": {
        "period": lambda p: p.get("period", p.get("lookback", None)),
        "entry_threshold": lambda p: p.get("overbought", p.get("oversold", p.get("threshold", None))),
        "cooling_bars": lambda p: p.get("cooling_period", 0),
    },
    "grid": {
        "grid_levels": lambda p: p.get("levels", p.get("grid_levels", 10)),
        "spacing": lambda p: p.get("grid_spacing", p.get("spacing", 0.5)),
        "coverage_ratio": lambda p: p.get("coverage", None),
    },
    "volume_based": {
        "period": lambda p: p.get("period", 20),
        "volume_threshold": lambda p: p.get("volume_mult", 1.5),
    },
}
```

#### 3.3.3 `_normalize_params()` 瀹炵幇閫昏緫

```python
def _normalize_params(self, method_name: str, raw_params: Dict[str, Any]) -> Dict[str, Any]:
    """灏嗗師濮嬪弬鏁板瓧鍏告槧灏勪负鏍囧噯鍖栧弬鏁般€?
    Args:
        method_name: 鏂规硶鍚嶏紙鐢ㄤ簬妫€娴嬬瓥鐣ョ被鍨嬶級銆?        raw_params: 鍘熷鍙傛暟蹇収銆?
    Returns:
        Dict: 鏍囧噯鍖栧弬鏁板瓧鍏革紝鍖呭惈:
          - strategy_type: 绛栫暐澶х被
          - 鍚勬爣鍑嗗寲瀛楁
          - _original_params_key: 鍘熷鍙傛暟瀛楀吀鐨?key 鍒楄〃锛堣皟璇曠敤锛?    """
    strategy_type = STRATEGY_TYPE_MAP.get(method_name, "unknown")
    rules = PARAM_NORMALIZATION_RULES.get(strategy_type, {})

    result = {
        "strategy_type": strategy_type,
        "_original_keys": list(raw_params.keys()),
    }

    for target_field, extractor in rules.items():
        try:
            value = extractor(raw_params)
            if value is not None:
                result[target_field] = value
        except (KeyError, TypeError, IndexError):
            pass  # 瀛楁涓嶅瓨鍦ㄦ椂涓嶅～鍏?
    return result
```

### 3.4 甯傚満鐘舵€佹爣璁?
#### 3.4.1 鑷姩鍒ゅ畾

褰撴彁渚?`market_data_provider` 鏃讹細

```python
def _determine_regime(
    self,
    entry_v1: KnowledgeEntry,
    extra: Optional[Dict] = None,
) -> str:
    """鍒ゅ畾甯傚満鐘舵€併€?
    浼樺厛绾э細
    1. extra["regime"]锛堟墜鍔ㄦ寚瀹氭渶楂樹紭鍏堬級
    2. market_data_provider锛堣嚜鍔ㄥ垽瀹氾級
    3. 鍥為€€绛栫暐锛氬熀浜?data_range 鍜?symbol 棰勪及
    4. 榛樿鍊?    """
    if extra and extra.get("regime"):
        return extra["regime"]

    if self._market_provider and entry_v1.data_range:
        try:
            return self._market_provider(
                entry_v1.symbol,
                entry_v1.data_range.split("~")[0],
            )
        except Exception:
            pass

    # 鍥為€€锛氬熀浜?insight_summary 涓殑 return_rate 姒傜巼鍒ゅ畾
    return "unknown"
```

#### 3.4.2 鎵嬪姩鎸囧畾

涓婂眰璋冪敤鏂癸紙濡傛姤鍛婃祦姘寸嚎 Step5 鎺ㄩ€佸墠锛夊彲浠庢姤鍛婁腑鍒嗘瀽 `regime`锛岄€氳繃 `extra` 浼犲叆銆?
### 3.5 鏍囩鑷姩鐢熸垚

```python
def _generate_tags(
    self,
    entry_v1: KnowledgeEntry,
    extra: Optional[Dict],
) -> List[str]:
    """鍩轰簬绛栫暐绫诲瀷銆佸弬鏁般€侀澶栦俊鎭敓鎴愬缁存爣绛俱€?
    鏍囩鏉ユ簮锛?    1. extra["tags"] 鎵嬪姩鏍囩锛堟渶楂樹紭鍏堬級
    2. PARAM_BASED_TAGS锛堝熀浜庡弬鏁扮殑鑷姩鏍囩锛?    3. 鍩轰簬 TIME_PERIOD_TAGS锛堝熀浜庡懆鏈熺殑鑷姩鏍囩锛?
    棰勮鏍囩灞傜骇锛?    - 绛栫暐绫诲瀷: trend / grid / mean_reversion / momentum / breakout
    - 鎶€鏈洜瀛? ma / macd / rsi / vwap / bollinger / volume / atr
    - 椋庢牸: long_only / short_term / swing / high_freq
    - 鍛ㄦ湡: short_term / mid_term / long_term
    """
    if extra and extra.get("tags"):
        return extra["tags"]

    tags = []
    method = entry_v1.method_name

    # 鏂规硶鍚?鈫?绛栫暐绫诲瀷鏍囩
    method_to_tag = {
        "ma_cross": "trend", "macd": "trend", "bollinger": "trend",
        "grid": "grid", "rsi": "mean_reversion",
        "kdj": "mean_reversion", "bias": "mean_reversion",
        "reversal": "mean_reversion",
        "vwap": "vwap", "obv": "volume",
    }
    tag = method_to_tag.get(method)
    if tag:
        tags.append(tag)

    # 鍩轰簬鍙傛暟鑷姩鎵撴妧鏈洜瀛愭爣绛?    params = entry_v1.params
    if "fast" in params and "slow" in params:
        tags.append("ma")
    if params.get("period", 0) <= 20:
        tags.append("short_term")
    elif params.get("period", 0) <= 60:
        tags.append("mid_term")
    else:
        tags.append("long_term")

    return list(set(tags))  # 鍘婚噸
```

### 3.6 quality_score 绠楁硶鍗囩骇

鍦ㄥ師鏈?`_compute_confidence` 鍩虹涓婂鍔犵ǔ瀹氭€у洜瀛愶細

```python
def _compute_quality_score(self, entry_v1: KnowledgeEntry) -> float:
    """缁煎悎璁＄畻璐ㄩ噺璇勫垎銆?
    鍏紡: quality_score = w1 脳 data_quality + w2 脳 stat_sig + w3 脳 stability
    鍏朵腑:
    - data_quality: 鏁版嵁璐ㄩ噺锛坣_bars銆侀鐜囥€佷俊鍙峰瘑搴︼級
    - stat_sig: 缁熻鏄捐憲鎬э紙鍥炴祴鏍锋湰閲忋€佽鐩栧懆鏈燂級
    - stability: 绋冲畾鎬э紙鑻ュ瓨鍦ㄥ巻鍙茶褰曪紝澶氭湡鐩镐技缁撴灉鐨勬柟宸€掓暟锛?
    涓?confidence 鐨勫叧绯伙細
    - confidence: 鍗曟鍥炴祴鐨勭疆淇″害锛堝厛楠岋級
    - quality_score: 缁撴瀯鍖栨秷璐圭淮搴︾殑璐ㄩ噺璇勪环锛堝悗楠岋紝鍚ǔ瀹氭€э級
    - 涓よ€呯嫭绔嬩絾涓嶅啿绐侊紝Bitable 涓兘鍙睍绀?    """
    # 澶嶇敤鐜版湁鐨?_compute_confidence 閫昏緫
    from engine.knowledge_bridge import _compute_confidence
    base = _compute_confidence(
        n_bars=...,
        data_frequency=entry_v1.data_frequency,
        signal_ratio=...,
    )

    # 鐭湡鍒嗘暟琛板噺锛堟秷璐圭鏇村叧娉ㄨ繎鏈熸暟鎹級
    # 鑻?completed_time 杈冩棭锛岄€傚綋闄嶅垎
    # ...

    return base
```

---

## 4. Bitable Schema 璁捐

### 4.1 寤鸿〃 SQL锛堢瓑浠峰瓧娈电粨鏋勶級

椋炰功 Bitable 閫氳繃 API 寤鸿〃锛岀瓑浠风殑瀛楁缁撴瀯濡備笅锛?
#### 琛ㄥ悕锛歚knowledge_entries`

**瀛楁娓呭崟锛堟寜鑱岃兘鍒嗙粍锛夛細**

| 搴忓彿 | Bitable 瀛楁鍚?| 绫诲瀷 | 蹇呭～ | 璇存槑 |
|:----:|:--------------|:----|:----:|:------|
| **鏍囪瘑缁?* |||||
| 1 | task_id | Text | 鉁?| 鍘婚噸閿箣涓€ |
| 2 | method_name | Text | 鉁?| 绛栫暐鏂规硶鍚?|
| 3 | symbol | Text | 鉁?| 鏍囩殑浠ｇ爜 |
| **鍒嗙被缁?* |||||
| 4 | regime | SingleSelect | | 閫夐」: bull/bear/sideways/volatile/unknown |
| 5 | timeframe | SingleSelect | | 閫夐」: 1d/4h/1h/15m/5m/1m |
| 6 | tags | MultiSelect | | 鑷敱鏍囩锛堝彲棰勮: 瓒嬪娍/鍙嶈浆/缃戞牸/鍔ㄩ噺锛?|
| **鏍稿績鎸囨爣缁?* |||||
| 7 | total_return | Number (鐧惧垎姣? | | 淇濈暀涓や綅灏忔暟 |
| 8 | sharpe | Number | | 淇濈暀涓や綅灏忔暟 |
| 9 | max_drawdown | Number (鐧惧垎姣? | | 淇濈暀涓や綅灏忔暟锛岃礋鏁拌〃绀轰簭鎹?|
| 10 | win_rate | Number (鐧惧垎姣? | | 0-100 |
| **璐ㄩ噺缁?* |||||
| 11 | quality_score | Number | | 0-1锛屼繚鐣欎袱浣嶅皬鏁?|
| 12 | confidence | Number | | 0-1锛屼繚鐣欎袱浣嶅皬鏁?|
| 13 | review_status | SingleSelect | | 閫夐」: pending/reviewed/rejected |
| **婧簮缁?* |||||
| 14 | source_run_id | Text | | 鍙烦杞埌 knowledge.db 璁板綍 |
| 15 | source_file | URL | | JSON 鏂囦欢閾炬帴 |
| **鍐呭缁?* |||||
| 16 | insight_summary | Text | | 缁撴瀯鍖栨憳瑕?|
| 17 | metadata | Text | | JSON 瀛楃涓诧紙distribution 绛夛級|
| 18 | normalized_params | Text | | JSON 瀛楃涓?|
| 19 | params | Text | | JSON 瀛楃涓诧紙鍘熷鍙傛暟蹇収锛?|
| **鏃堕棿缁?* |||||
| 20 | data_range | Text | | 濡?"2025-01-01~2025-12-31" |
| 21 | completed_time | DateTime | | 鎵ц瀹屾垚鏃堕棿 |
| 22 | created_at | DateTime | | 鍒涘缓鏃堕棿锛堣嚜鍔級 |
| 23 | updated_at | DateTime | | 鏇存柊鏃堕棿锛堣嚜鍔級 |
| **绯荤粺缁?* |||||
| 24 | _schema_version | Text | 鉁?| schema 鐗堟湰鍙凤紝鍒濆 "v1.0" |

### 4.2 椋炰功 Bitable API 鍒涘缓瀛楁

#### 鎵归噺鍒涘缓绛栫暐

```python
# sync_to_bitable.py 涓敤鍒扮殑瀛楁鍒涘缓閫昏緫

FIELDS_TO_CREATE = [
    {"field_name": "task_id",         "type": 1},   # Text
    {"field_name": "method_name",     "type": 1},   # Text
    {"field_name": "symbol",          "type": 1},   # Text
    {"field_name": "regime",          "type": 3,    # SingleSelect
     "property": {
         "options": [
             {"name": "bull",      "color": 0},  # 绾㈣壊
             {"name": "bear",      "color": 1},  # 娣辩孩
             {"name": "sideways",  "color": 2},  # 姗欒壊
             {"name": "volatile",  "color": 3},  # 榛勮壊
             {"name": "unknown",   "color": 9},  # 鐏拌壊
         ]
     }},
    {"field_name": "timeframe",       "type": 3,    # SingleSelect
     "property": {
         "options": [
             {"name": "1d",  "color": 5},
             {"name": "4h",  "color": 6},
             {"name": "1h",  "color": 7},
             {"name": "15m", "color": 8},
         ]
     }},
    {"field_name": "tags",            "type": 4},   # MultiSelect
    {"field_name": "total_return",    "type": 2},   # Number
    {"field_name": "sharpe",          "type": 2},   # Number
    {"field_name": "max_drawdown",    "type": 2},   # Number
    {"field_name": "win_rate",        "type": 2},   # Number
    {"field_name": "quality_score",   "type": 2},   # Number
    {"field_name": "confidence",      "type": 2},   # Number
    {"field_name": "review_status",   "type": 3,    # SingleSelect
     "property": {
         "options": [
             {"name": "pending",   "color": 9},   # 鐏拌壊
             {"name": "reviewed",  "color": 5},   # 缁胯壊
             {"name": "rejected",  "color": 0},   # 绾㈣壊
         ]
     }},
    {"field_name": "source_run_id",   "type": 1},   # Text
    {"field_name": "source_file",     "type": 15},  # URL
    {"field_name": "insight_summary", "type": 1},   # Text
    {"field_name": "metadata",        "type": 1},   # Text
    {"field_name": "normalized_params", "type": 1}, # Text
    {"field_name": "params",          "type": 1},   # Text
    {"field_name": "data_range",      "type": 1},   # Text
    {"field_name": "completed_time",  "type": 5},   # DateTime
    {"field_name": "created_at",      "type": 5},   # DateTime
    {"field_name": "updated_at",      "type": 5},   # DateTime
    {"field_name": "_schema_version", "type": 1},   # Text
]
```

### 4.3 Bitable 棰勮瑙嗗浘

Bitable 寤鸿棰勮 3 涓鍥撅細

| 瑙嗗浘 | 閫傜敤浜虹兢 | 杩囨护鏉′欢 | 鎺掑簭 |
|:-----|:---------|:---------|:------|
| **鍏ㄩ儴璁板綍** | 绠＄悊鍛?| 鏃?| 鎸?created_at 闄嶅簭 |
| **寰呭鏍?* | 澧ㄦ兜 | review_status = pending | 鎸?quality_score 鍗囧簭 |
| **楂樿川閲忕煡璇?* | 鎵€鏈変汉 | quality_score >= 0.7 AND review_status = reviewed | 鎸?sharpe 闄嶅簭 |

---

## 5. BitableSync 鍚屾鍣ㄨ璁?
> 鈿狅笍 **渚濊禆鏉′欢锛?* 椋炰功 App 闇€娣诲姞 `bitable:bitable` 鏉冮檺骞堕噸鏂板彂甯冿紝鍚﹀垯 Bitable 鍚屾 API 璋冪敤灏嗗け璐ャ€?
### 5.1 鎺ュ彛瀹氫箟

```python
class BitableSync:
    """Bitable 鍚屾鍣?鈥?灏?KnowledgeEntry v2 鍚屾鍒伴涔?Bitable銆?
    鑱岃矗锛?    1. 澧為噺鍚屾锛氭柊澧?鏇存柊鐭ヨ瘑鏉＄洰鍒?Bitable
    2. 鍘婚噸锛氬熀浜?(task_id, method_name, symbol) 缁勫悎閿?    3. 閲嶈瘯锛氶涔?API 涓嶇ǔ瀹氭椂鐨勬寚鏁伴€€閬块噸璇?    4. schema_version锛氳拷韪瓧娈垫紨杩?    5. 鍥炲～鏀寔锛氭壒閲忎粠 knowledge.db / JSON 鏂囦欢閲嶅缓 Bitable
    """

    def __init__(
        self,
        app_token: str,
        table_id: str,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        batch_size: int = 10,
    ):
        """鍒濆鍖?Bitable 鍚屾鍣ㄣ€?
        Args:
            app_token: Bitable app_token銆?            table_id: 琛?ID銆?            max_retries: API 璋冪敤鏈€澶ч噸璇曟鏁帮紙榛樿 3锛夈€?            backoff_base: 鎸囨暟閫€閬垮熀鏁扮鏁帮紙榛樿 1.0锛夈€?            batch_size: 鎵归噺鍐欏叆鎵规澶у皬锛堥粯璁?10锛夈€?        """
        self.app_token = app_token
        self.table_id = table_id
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.batch_size = batch_size
        self._cache = {}  # (task_id, method_name, symbol) 鈫?record_id
        """缂撳瓨宸插悓姝ョ殑璁板綍 ID锛屽幓閲嶇敤銆?""

    # 鈹€鈹€鈹€ 鏍稿績锛氬悓姝ュ崟鏉¤褰?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def sync_one(
        self,
        entry: KnowledgeEntryV2,
        dry_run: bool = False,
    ) -> Optional[str]:
        """鍚屾鍗曟潯鐭ヨ瘑鏉＄洰鍒?Bitable銆?
        Args:
            entry: KnowledgeEntry v2 鏉＄洰銆?            dry_run: 浠呮墦鍗帮紝涓嶅疄闄呭啓鍏ャ€?
        Returns:
            Optional[str]: 鍐欏叆鎴愬姛鍚庣殑 record_id锛屽け璐ヨ繑鍥?None銆?
        Raises:
            ValueError: entry 蹇呭～瀛楁缂哄け銆?        """
        ...
```

### 5.2 鍘婚噸鏈哄埗

#### 5.2.1 鍘婚噸閿?
```
澶嶅悎鍘婚噸閿? (task_id, method_name, symbol)
```

#### 5.2.2 鍘婚噸娴佺▼

```
                          鈹屸攢鈹€鈹€鈹€鈹€鈹?                          鈹?鏂癳ntry 鈹?                          鈹斺攢鈹€鈹攢鈹€鈹?                             鈹?                    鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                    鈹?缂撳瓨涓凡瀛樺湪锛?    鈹?                    鈹?(task_id, method,鈹?                    鈹? symbol)         鈹?                    鈹斺攢鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹?                   YES  鈹?     鈹? NO
                        鈹?     鈹?              鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攼    鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?              鈹?鏌?Bitable 鈹?   鈹?create_record()  鈹?              鈹?get_record 鈹?   鈹?锛堟柊澧烇級           鈹?              鈹? 姣斿 updated_at 鈹?                 鈹?              鈹斺攢鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹?   鈹斺攢鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€-鈹?                    鈹?                鈹?                    鈹?闇€瑕佹洿鏂?        鈹?              鈹屸攢鈹€鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹€鈹€鈹?        鈹?              鈹?update_record()      鈹?              鈹?锛堟洿鏂板瓧娈碉級          鈹?              鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?        鈹?                                     鈹?                          鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                          鈹?鏇存柊缂撳瓨 + 杩斿洖      鈹?                          鈹?record_id           鈹?                          鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

#### 5.2.3 缂撳瓨鍒濆鍖?
```python
def init_cache(self) -> Dict[str, str]:
    """浠?Bitable 鍏ㄩ噺鎷夊彇宸叉湁璁板綍锛屽垵濮嬪寲鍐呭瓨缂撳瓨銆?
    棣栨浣跨敤鏃惰皟鐢紝閬垮厤姣忔 sync 閮芥煡 Bitable銆?    缂撳瓨 key = f"{task_id}:{method_name}:{symbol}"
    缂撳瓨 value = record_id

    Returns:
        Dict[str, str]: 鍘婚噸缂撳瓨鏄犲皠銆?    """
    records = self._list_all_records()
    for record in records:
        fields = record.get("fields", {})
        key = f"{fields.get('task_id','')}:{fields.get('method_name','')}:{fields.get('symbol','')}"
        self._cache[key] = record["record_id"]
    return self._cache
```

### 5.3 閲嶈瘯鏈哄埗

#### 5.3.1 鎸囨暟閫€閬?
```python
def _retry_with_backoff(self, api_call: Callable, **kwargs) -> Any:
    """椋炰功 API 鎸囨暟閫€閬块噸璇曞皝瑁呫€?
    閲嶈瘯鏉′欢锛?    - HTTP 429锛堣姹傞檺娴侊級
    - HTTP 5xx锛堟湇鍔＄閿欒锛?    - 缃戠粶瓒呮椂锛坮equests.Timeout锛?
    閫€閬跨瓥鐣ワ細
    - 绗?1 娆￠噸璇? 绛夊緟 1s
    - 绗?2 娆￠噸璇? 绛夊緟 2s
    - 绗?3 娆￠噸璇? 绛夊緟 4s
    - 绗?4 娆￠噸璇? 绛夊緟 8s 鍚庢斁寮?    - 绗?1 娆￠噸璇? 绛夊緟 1s
    - 绗?2 娆￠噸璇? 绛夊緟 2s
    - 绗?3 娆￠噸璇? 绛夊緟 4s

    鏈€澶ч噸璇曟鏁?= max_retries
    """
    import time
    from requests.exceptions import Timeout, RequestException

    for attempt in range(self.max_retries + 1):
        try:
            return api_call(**kwargs)
        except (Timeout, RequestException) as e:
            if attempt >= self.max_retries:
                logger.error("API call failed after %d retries: %s", attempt, e)
                raise
            wait = self.backoff_base * (2 ** attempt)
            logger.warning(
                "API call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, self.max_retries, wait, e,
            )
            time.sleep(wait)
```

### 5.4 鏇存柊绛栫暐

| 鏇存柊绫诲瀷 | 瑙﹀彂鏉′欢 | 鎿嶄綔 |
|:---------|:---------|:------|
| **append**锛堥粯璁わ級| 鏂?task_id + method + symbol | `create_record()` |
| **update**锛坢erge锛墊 宸叉湁 task_id + method + symbol | `update_record()`锛堝悎骞跺瓧娈?+ 鎵╁睍 metadata锛墊
| **overwrite** | 绠＄悊鍛樻墜鍔ㄨЕ鍙戝叏閲忛噸寤?| 鍏堟竻绌鸿〃锛屽啀閲嶆柊鍐欏叆 |

#### 5.4.1 merge 瑙勫垯

鏇存柊鏃堕噰鐢?*鏅鸿兘瑕嗙洊**锛?
```
metadata = merge_dict(
    old_metadata,      # 鍘熸潵鐨?JSON 鍐呭
    new_metadata,      # 鏂?JSON 鍐呭
    strategy="merge"   # 鍚?key: 鏂板€艰鐩栨棫鍊? 鏂?key: 杩藉姞; 鏃?key 淇濈暀
)
```

### 5.5 schema_version 鏍￠獙

姣忔鍚屾鍓嶆鏌?Bitable 鐨?schema_version锛?
```python
def check_schema_compatibility(self) -> bool:
    """鏍￠獙褰撳墠 Bitable schema 鏄惁鍏煎銆?
    浠?Bitable 琛ㄥご鐨?description 鍏冧俊鎭腑璇诲彇 schema_version銆?    鑻?Bitable schema_version < 浠ｇ爜瑕佹眰鐨勬渶浣庣増鏈?鈫?杩斿洖 False + 鏃ュ織鍛婅銆?    鑻?Bitable schema_version >= 浠ｇ爜瑕佹眰鐗堟湰 鈫?杩斿洖 True銆?
    Returns:
        bool: 鍏煎杩斿洖 True锛屼笉鍏煎杩斿洖 False銆?    """
    required_version = "v1.0"
    bitable_schema = self._get_bitable_schema()
    if not bitable_schema:
        logger.warning("鏃犳硶璇诲彇 Bitable schema 鐗堟湰")
        return False
    if bitable_schema < required_version:
        logger.error(
            "Bitable schema_version=%s < required=%s锛岃鍗囩骇 Bitable 瀛楁",
            bitable_schema, required_version,
        )
        return False
    return True
```

### 5.6 鎵归噺鍜屽洖濉敮鎸?
```python
def sync_batch(
    self,
    entries: List[KnowledgeEntryV2],
    progress_callback: Optional[Callable] = None,
) -> Dict[str, int]:
    """鎵归噺鍚屾澶氭潯鐭ヨ瘑鏉＄洰鍒?Bitable銆?
    Args:
        entries: 寰呭悓姝ョ殑 v2 鏉＄洰鍒楄〃銆?        progress_callback: 杩涘害鍥炶皟鍑芥暟锛堝彲閫夛級锛岀鍚嶏細
          def cb(current: int, total: int, message: str) -> None

    Returns:
        Dict[str, int]: {"synced": n, "skipped": m, "failed": k}
    """
    result = {"synced": 0, "skipped": 0, "failed": 0}

    for i, entry in enumerate(entries):
        try:
            record_id = self.sync_one(entry)
            if record_id:
                result["synced"] += 1
            else:
                result["skipped"] += 1
        except Exception:
            result["failed"] += 1

        if progress_callback:
            progress_callback(i + 1, len(entries), f"姝ｅ湪鍚屾: {entry.task_id}")

    return result

def backfill_from_storage(
    self,
    storage_dir: str = DEFAULT_STORAGE_DIR,
    dry_run: bool = False,
) -> int:
    """浠?knowledge_entries JSON 鏂囦欢鐩綍鎵归噺鍥炲～ Bitable銆?
    閬嶅巻 storage_dir 涓嬬殑鎵€鏈?knowledge_*.json 鏂囦欢锛?    瑙ｆ瀽涓?KnowledgeEntryV2锛堣嫢涓?v1 鍒欏厛閫氳繃 Normalizer 鍗囩骇锛夛紝
    鐒跺悗璋冪敤 sync_batch() 鍐欏叆 Bitable銆?
    Args:
        storage_dir: knowledge_entries JSON 鐩綍璺緞銆?        dry_run: 浠呮墦鍗帮紝涓嶅疄闄呭啓鍏ャ€?
    Returns:
        int: 鎴愬姛鍚屾鐨勬潯鐩暟銆?    """
    ...
```

### 5.7 鍚屾鏃ュ織

姣忔鍚屾鎿嶄綔璁板綍鍒?`logs/bitable_sync_{YYYYMMDD}.log`锛?
```plain
===== BitableSync Report 2026-05-17 12:30:00 =====
Status: SUCCESS
Synced: 12
Skipped (duplicate): 2
Failed: 0
Duration: 3.2s
Retries: 2 (2 tasks retried)
```

---

## 6. 鏁版嵁娴佸叏鏅?
### 6.1 瀹屾暣鏁版嵁绠￠亾

```
                          Layer 1 (鏁版嵁婧愬眰 - 鍥炴祴浜у嚭)
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? BacktestResult + StrategyContext                                鈹?鈹?   鈫?KnowledgeBridge.harvest()                                   鈹?鈹?   鈫?knowledge_entries (JSON 鏂囦欢: knowledge_{task_id}.json)     鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                            鈹?                            鈹?瑙﹀彂: 鍥炴祴瀹屾垚 / 瀹氭椂浠诲姟 / 浜哄伐瑙﹀彂
                            鈻?                          Layer 1.5 (鏍囧噯鍖栧眰 - 鏂板)
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? KnowledgeNormalizer.normalize(entry_v1)                        鈹?鈹?   鈫?鍙傛暟鏍囧噯鍖?(strategy_type + unified params)                  鈹?鈹?   鈫?甯傚満鐘舵€佹爣璁?(regime)                                        鈹?鈹?   鈫?鏍囩鐢熸垚 (tags)                                              鈹?鈹?   鈫?鏍稿績鎸囨爣鎻愬彇 (return/sharpe/drawdown/win_rate)              鈹?鈹?   鈫?quality_score 璁＄畻                                          鈹?鈹?   鈫?KnowledgeEntry v2 (鏍囧噯鍖栨潯鐩?                               鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                            鈹?                            鈻?                          Layer 2 (鍚屾灞?- 鏂板)
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? BitableSync.sync_one(v2_entry)                                 鈹?鈹?   鈫?schema_version 鏍￠獙                                         鈹?鈹?   鈫?鍘婚噸妫€鏌?(task_id:method:symbol)                             鈹?鈹?   鈫?椋炰功 API 璋冪敤 (create / update)                              鈹?鈹?   鈫?鎸囨暟閫€閬块噸璇?                                               鈹?鈹?   鈫?鏃ュ織鍐欏叆                                                    鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                            鈹?                            鈻?                          Layer 3 (灞曠ず灞?- 椋炰功)
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Feishu Bitable: 鐭ヨ瘑鏉＄洰灞曠ず                                    鈹?鈹?   鈫?鍏ㄩ儴璁板綍瑙嗗浘 (榛樿闄嶅簭)                                      鈹?鈹?   鈫?寰呭鏍歌鍥?(review_status=pending)                          鈹?鈹?   鈫?楂樿川閲忕煡璇嗚鍥?(quality_score >= 0.7)                        鈹?鈹?   鈫?鏍囩杩囨护銆佸缁村害鎺掑簭銆佸瓧娈靛姣?                              鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                            鈹?                            鈻?(Phase 3)
                          Layer 4 (鐭ヨ瘑鍒嗘瀽灞?
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Knowledge Analysis Engine                                      鈹?鈹?   鈫?鍙傛暟绋冲畾鎬ф帓搴?                                            鈹?鈹?   鈫?绛栫暐鑱氱被鍒嗘瀽                                                鈹?鈹?   鈫?妯℃澘鍖栨憳瑕侊紙缁熻瑙勫垯闈炵敓鎴愬紡锛?                              鈹?鈹?   鈫?鏉′欢瑙勫緥鍙戠幇 (regime 脳 strategy 脳 performance)              鈹?鈹?   鈫?鐭ヨ瘑鍥捐氨 (鏈潵)                                             鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

### 6.2 涓夌瑙﹀彂妯″紡

| 妯″紡 | 瑙﹀彂鏉′欢 | 鎵ц鍐呭 |
|:-----|:---------|:---------|
| **瀹炴椂瑙﹀彂** | 姣忔鍥炴祴瀹屾垚锛圧unner 灏撅級| harvest() 鈫?normalize() 鈫?sync_one() |
| **瀹氭椂鍚屾** | 瀹氭椂浠诲姟锛堝姣忓皬鏃讹級 | 鎵弿 storage_dir 涓湭鍚屾鐨?JSON 鈫?鎵归噺 sync |
| **鍏ㄩ噺鍥炲～** | 浜哄伐瑙﹀彂 / 鍒濆寤鸿〃 | backfill_from_storage() 鈫?鍏ㄩ噺瑕嗙洊 |

### 6.3 澶辫触澶勭悊

```
                                         鈹屸攢鈹€鈹€鈹€鈹€鈹?                                         鈹?鍚屾澶辫触 鈹?                                         鈹斺攢鈹€鈹攢鈹€鈹?                                            鈹?                                   鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                   鈹?鏄惁鍙噸璇曪紵       鈹?                                   鈹?(429 / 5xx / 瓒呮椂)鈹?                                   鈹斺攢鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹?                                  YES  鈹?     鈹? NO
                                       鈹?     鈹?                              鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攼    鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                              鈹?鎸囨暟閫€閬? 鈹?   鈹?鍐欏叆 failed_queue    鈹?                              鈹?3娆″唴閲嶈瘯  鈹?   鈹?(local JSON)        鈹?                              鈹斺攢鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹?   鈹?next sync 閲嶈瘯       鈹?                                   鈹?         鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                                   鈹?                              鈹屸攢鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹?                              鈹?3娆′粛澶辫触 鈹?                              鈹斺攢鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹?                                   鈹?                           鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈻尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                           鈹?鍐欏叆 failed_queue 鈹?                           鈹?+ 鏃ュ織鍛婅       鈹?                           鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

---

## 7. 鍒嗗眰鎺ㄨ繘绛栫暐

### 7.1 Phase 1锛氱粨鏋勫寲鐭ヨ瘑 + Bitable 鍙锛堝厛鍋氾級

**鍘熷垯锛氫笉瑕佹€?AI锛屽厛鍋氱粨鏋勫寲鐭ヨ瘑銆?*

Phase 1 鎷嗕负 3 涓瓙闃舵锛岄€愭鎺ㄨ繘锛?
#### Phase 1a锛氬崗璁笌鏍囧噯鍖栵紙3d锛?
| 浠诲姟 | 浜や粯鐗?| 棰勪及宸ユ椂 |
|:-----|:-------|:---------|
| KnowledgeEntry v2 鍗忚 | `knowledge_bridge_v2.py`锛堜粠闆跺垱寤?dataclass + 鏍￠獙 + JSON 搴忓垪鍖栵級| 2d |
| KnowledgeNormalizer 缁勪欢 | `knowledge_normalizer.py`锛堝弬鏁版爣鍑嗗寲鏄犲皠 + 甯傚満鐘舵€佹爣璁?+ 鏍囩鐢熸垚 + quality_score锛墊 1d |
| **Phase 1a 鎬昏** | | **3d** |

**Phase 1a 楠屾敹锛?* v2 鍗忚鍙垱寤?鏍￠獙锛孨ormalizer 鍙皢鍘熷杈撳叆鏍囧噯鍖栦负 v2 鏍煎紡

#### Phase 1b锛欱itable 鍚屾锛?d锛?
| 浠诲姟 | 浜や粯鐗?| 棰勪及宸ユ椂 |
|:-----|:-------|:---------|
| Bitable 寤鸿〃 | 椋炰功 Bitable 鍒涘缓 + 24 瀛楁閰嶇疆 | 0.5d |
| BitableSync 鍚屾鍣紙鏍稿績锛?| `bitable_sync.py`锛堝閲忓悓姝?+ 閲嶈瘯 + 鍘婚噸寮曟搸锛墊 2d |
| 鍥炲～鑴氭湰 | `backfill_bitable.py`锛堜粠 JSON 鏂囦欢鐩綍鎵归噺鍥炲～ Bitable锛墊 0.5d |
| **Phase 1b 鎬昏** | | **3d** |

**Phase 1b 楠屾敹锛?* 鍗曟潯鐭ヨ瘑鍙悓姝ュ埌 Bitable锛屽幓閲嶉獙璇侀€氳繃锛岄噸璇曟満鍒堕獙璇侀€氳繃

#### Phase 1c锛歊unner 鎺ュ叆 + 楠屾敹锛?d锛?
> 鈿狅笍 **渚濊禆鏉′欢锛?* Phase 1b Bitable 鍚屾缁勪欢灏辩华鍚庯紝鎺ュ叆 Runner 鏃堕渶纭繚椋炰功 App 宸叉坊鍔?`bitable:bitable` 鏉冮檺

| 浠诲姟 | 浜や粯鐗?| 棰勪及宸ユ椂 |
|:-----|:-------|:---------|
| 鍥炴祴鍚庡疄鏃跺悓姝ユ帴鍏?| 鍦?Runner 灏鹃儴璋冪敤 sync_one() | 0.5d |
| 瀹氭椂鍚屾鑴氭湰 | 鎵弿鏈悓姝?JSON 鈫?鎵归噺 sync锛堟浛浠ｆ柟妗堬級| 0.5d |
| 涓撳璇勫 + 鐭ヨ瘑瀹℃煡 | 浠ｇ爜璇勫 + 鐭ヨ瘑鏉＄洰瀹℃牳 | 1d |
| **Phase 1c 鎬昏** | | **2d** |

**Phase 1 鎬昏锛?d + 3d + 2d = 8d**

**Phase 1 鏁翠綋楠屾敹鏍囧噯锛?*
- [ ] KnowledgeEntry v2 鍗忚鍙甯稿垱寤?+ 鏍￠獙
- [ ] KnowledgeNormalizer 鑳藉皢鍘熷杈撳叆鍗囩骇涓?v2锛堝惈鍙傛暟鏍囧噯鍖?+ 鏍囩 + 鏍稿績鎸囨爣鎻愬彇锛?- [ ] Bitable 琛ㄥ凡鍒涘缓锛屾墍鏈?24 涓瓧娈靛氨缁?- [ ] 鍗曟潯鐭ヨ瘑鍙甯稿悓姝ュ埌 Bitable
- [ ] 鍘婚噸鏈哄埗楠岃瘉閫氳繃锛堝悓涓€ task_id+method+symbol 涓嶄細閲嶅鍒涘缓璁板綍锛?- [ ] 閲嶈瘯鏈哄埗楠岃瘉閫氳繃锛堟ā鎷?429 閿欒鍚庤嚜鍔ㄩ噸璇曟垚鍔燂級
- [ ] 鍏ㄩ噺鍥炲～鑴氭湰鍙壂鎻忓巻鍙?knowledge_entries JSON 鏂囦欢骞跺啓鍏?Bitable

### 7.2 Phase 2锛氭悳绱€佹爣绛俱€佽繃婊?
| 浠诲姟 | 浜や粯鐗?| 棰勪及宸ユ椂 |
|:-----|:-------|:---------|
| Bitable 鎼滅储瑙嗗浘浼樺寲 | 棰勮鎼滅储瑙嗗浘 | 0.5d |
| 鏍囩浣撶郴瀹屽杽 | 鏍囩绠＄悊 + 鑷姩鏍囩瑙勫垯浼樺寲 | 1d |
| 澶氱淮鎺掑簭瀵规瘮 | Bitable 瑙嗗浘棰勮锛堟寚鏍囧垪鎺掑簭锛?| 0.5d |
| 鐭ヨ瘑鍗＄墖浼樺寲 | 椋炰功鐭ヨ瘑鍗＄墖鏄剧ず鏍煎紡 | 1d |
| **Phase 2 鎬昏** | | **3d** |

**Phase 2 楠屾敹鏍囧噯锛?*
- [ ] 鍙€氳繃 Bitable 鎼滅储妗嗘寜鍏抽敭璇嶆绱㈢煡璇?- [ ] 鍙€氳繃 tags 澶氶€夎繃婊?- [ ] 鍙寜 sharpe / total_return / quality_score 鎺掑簭
- [ ] 鐭ヨ瘑鍗＄墖灞曠ず鏍煎紡娓呮櫚鍙

### 7.3 Phase 3锛氬弬鏁扮ǔ瀹氭€у垎鏋?+ 绛栫暐鑱氱被 + 瑙勫緥鍙戠幇

**鍘熷垯锛氫笉鍋?AI 鐢熸垚寮忔憳瑕侊紙閬垮厤骞昏锛夛紝鎵€鏈夊垎鏋愬熀浜庣粺璁¤鍒欏拰妯℃澘鍖栬緭鍑恒€?*

| 浠诲姟 | 浜や粯鐗?| 棰勪及宸ユ椂 |
|:-----|:-------|:---------|
| 鍙傛暟绋冲畾鎬у垎鏋?| 鑱氬悎鍚屼竴 method + symbol 澶氱粍鍙傛暟鐨勬晥鏋滄帓搴忥紙鍩轰簬鏂瑰樊/澶忔櫘绋冲畾鎬э級 | 2d |
| 绛栫暐鑱氱被 | 鎸?method_name + regime + 鏁堟灉鎸囨爣鑷姩鑱氱被锛堝熀浜庣粺璁¤窛绂伙級 | 1.5d |
| 妯℃澘鍖栨憳瑕侊紙闈炵敓鎴愬紡锛?| 鍩轰簬缁熻瑙勫垯鐨勫浐瀹氭ā鏉胯緭鍑猴紙鍙傛暟鍖洪棿/鍒嗕綅/鑳滅巼鑼冨洿锛?| 1d |
| 鏉′欢瑙勫緥鍙戠幇 | "浣庢尝鍔ㄦ椂 MA绫昏〃鐜版洿濂? 绫昏鍒欐寲鎺橈紙鍩轰簬鏉′欢鍒嗗竷缁熻锛?| 1.5d |
| **Phase 3 鎬昏** | | **6d** |

**Phase 3 楠屾敹鏍囧噯锛?*
- [ ] 鍙寜绋冲畾鎬ф帓搴忓悓涓€鏂规硶鐨勫弬鏁伴厤缃?- [ ] 鍙嚜鍔ㄥ彂鐜扮浉浼肩瓥鐣ヨ仛绫?- [ ] 鍙緭鍑?"鍦?XX 甯傚満鐘舵€佷笅锛孹X 绛栫暐琛ㄧ幇鏇村ソ" 绫昏鍒?- [ ] 妯℃澘鍖栨憳瑕佸唴瀹瑰噯纭紝鏃犵敓鎴愬紡鍐呭

---

## 8. 宸ヤ綔閲忚瘎浼版眹鎬?
| 缁勪欢 | 浠ｇ爜琛屼及绠?| 鍗曞厓娴嬭瘯鏁?| 棰勪及宸ユ椂 | 渚濊禆 |
|:-----|:---------|:---------|:---------|:------|
| **Phase 1a锛氬崗璁笌鏍囧噯鍖?* | | | **3d** | |
| KnowledgeEntry v2 鍗忚 | ~100 琛?| 5 | 2d | 浠庨浂鍒涘缓 |
| KnowledgeNormalizer | ~250 琛?| 8 | 1d | v2 鍗忚 |
| **Phase 1b锛欱itable 鍚屾** | | | **3d** | |
| Bitable 寤鸿〃 | ~50 琛?(API 璋冪敤) | 2 | 0.5d | 椋炰功鏉冮檺 + bitable:bitable |
| BitableSync 鏍稿績 | ~300 琛?| 10 | 2d | 椋炰功 API token |
| 鍥炲～鑴氭湰 | ~200 琛?| 3 | 0.5d | v2 鍗忚 |
| **Phase 1c锛歊unner 鎺ュ叆** | | | **2d** | |
| Runner 灏鹃儴闆嗘垚 | ~50 琛?| 1 | 0.5d | BitableSync |
| 瀹氭椂鍚屾鑴氭湰 | ~150 琛?| 2 | 0.5d | BitableSync |
| 涓撳璇勫 + 鐭ヨ瘑瀹℃煡 | 鈥?| 鈥?| 1d | 鎵€鏈夌粍浠?|
| **Phase 1 鎬昏** | **~1,100 琛?* | **~31** | **8d** | |
| Phase 2锛堟悳绱€佽繃婊ゃ€佽鍥撅級 | ~200 琛?| 5 | 3d | Phase 1 |
| Phase 3锛堝弬鏁扮ǔ瀹氭€?+ 鑱氱被 + 妯℃澘鎽樿 + 瑙勫緥鍙戠幇锛墊 ~500 琛?| 8 | 6d | Phase 1+2 |
| **鍏ㄩ」鐩€昏** | **~1,800 琛?* | **~44** | **17d** | |

---

## 9. 椋庨櫓涓庡喅绛?
### 9.1 椋庨櫓鐭╅樀

| # | 椋庨櫓 | 姒傜巼 | 褰卞搷 | 缂撹В鎺柦 |
|:-:|:-----|:----:|:----:|:---------|
| 1 | 椋炰功 API 闄愭祦锛?29锛墊 楂?| 涓?| 鎸囨暟閫€閬?+ 澶辫触闃熷垪 |
| 2 | Bitable 瀛楁鏃犳硶鍏ㄩ儴鍖归厤 | 涓?| 涓?| Text 瀛楁鍏滃簳瀛樺偍 JSON |
| 3 | knowledge_entries JSON 鏂囦欢鎹熷潖 | 浣?| 楂?| 鏍￠獙 + 鍛婅锛屽洖濉椂璺宠繃 |
| 4 | schema 婕旇繘鍚庢棫璁板綍涓嶅吋瀹?| 涓?| 涓?| schema_version 杩借釜 + 鍗囩骇鑴氭湰 |
| 5 | 鍥炲～鑴氭湰鍐欏叆閲忚繃澶цЕ鍙戦檺娴?| 涓?| 楂?| batch 鍒嗘壒 + 闂撮殧鎺у埗 |
| 6 | 椋炰功 Bitable 绌洪棿鏉冮檺鍙樻洿 | 浣?| 楂?| token 杩囨湡鑷姩鍛婅 |

### 9.2 鍏抽敭鍐崇瓥璁板綍

| 鍐崇瓥 | 閫夐」 | 閫夋嫨 | 鐞嗙敱 |
|:-----|:-----|:-----|:------|
| 瀛樺偍鏍煎紡 | JSON file vs Bitable API 鍙屽啓 | 鍙屽啓 | 淇濈暀鏂囦欢绾ф寔涔呭寲锛孊itable 浠呭仛灞曠ず娑堣垂 |
| 鍘婚噸閿?| task_id vs (task_id, method, symbol) | 缁勫悎閿?| 鍚屼竴 task 鍙惈澶氫釜鏂规硶 |
| 鏇存柊绛栫暐 | append vs overwrite vs merge | merge | 鏇存柊鏃朵繚鐣欐棫瀛楁 + 鍚堝苟 metadata |
| quality_score 绠楁硶 | 鏂板啓 vs 澶嶇敤 confidence | 鍗囩骇澶嶇敤 | 澶嶇敤鐜版湁缃俊搴﹂€昏緫 + 澧炲姞绋冲畾鎬у洜瀛?|
| 鏃堕棿妗嗘灦 | 鑷姩鎺ㄦ柇 vs 鎵嬪姩鎸囧畾 | 浼樺厛鎵嬪姩 | Bitable SingleSelect 鍐冲畾鎵嬪姩鎸囧畾鏇村彲闈?|
| Bitable 涓婚敭 | 椋炰功鑷姩 ID vs 鑷畾涔?key | 椋炰功鑷姩 | Bitable 涓嶆敮鎸佽嚜瀹氫箟涓婚敭锛岀敤鍘婚噸閿煡閲?|
| Phase 鎺ㄨ繘鏉′欢 | 鏃堕棿 vs 鍔熻兘 | 鍔熻兘瀹屾垚 | Phase 1 楠屾敹閫氳繃鍚庢墠鑳藉紑濮?Phase 2 |

### 9.3 Phase 鎺ㄨ繘鏉′欢锛堥棬绂侊級

```
Phase 1 閫氳繃闂ㄧ:
  鈻?鍘婚噸鏈哄埗楠岃瘉閫氳繃
  鈻?鑷冲皯 10 鏉＄煡璇嗗悓姝ュ埌 Bitable
  鈻?鍚屾閲嶈瘯鏈哄埗楠岃瘉閫氳繃
  鈻?鐭ヨ瘑鍗＄墖灞曠ず鏍煎紡绗﹀悎瑕佹眰
  鈫?鎵瑰噯 Phase 2

Phase 2 閫氳繃闂ㄧ:
  鈻?鎼滅储鍔熻兘鍙敤
  鈻?鏍囩杩囨护鍔熻兘鍙敤
  鈻?澶氱淮鎺掑簭鍔熻兘鍙敤
  鈫?鎵瑰噯 Phase 3

Phase 3 閫氳繃闂ㄧ:
  鈻?Phase 1+2 绉疮 鈮?500 鏉＄粨鏋勫寲鐭ヨ瘑鏉＄洰
  鈻?鑷冲皯鏈?5 绉嶄笉鍚岀瓥鐣ョ殑鍥炴祴鏁版嵁
  鈻?瑕嗙洊鑷冲皯 3 绉?regime 鐘舵€?  鈫?鍚姩 Knowledge Analysis Layer 寮€鍙?```

---

## 10. 涓庡綋鍓嶇郴缁熺殑鍏煎鎬?
### 10.1 涓庣幇鏈?KnowledgeBridge 鐨勫叧绯?
- `KnowledgeBridge` 绫荤殑 `harvest()` 鏂规硶鎸?import 鏂瑰紡浣跨敤锛屾棤闇€淇敼
- `KnowledgeEntry` v2 鍗忚浠庨浂鍒涘缓锛屼笉渚濊禆 v1 dataclass 鐨勫師鍦颁繚鐣?- `KnowledgeNormalizer.normalize()` 鎺ユ敹鍥炴祴鍘熷杈撳嚭浣滀负杈撳叆锛岃緭鍑?v2
- 鏂囦欢瀛樺偍璺緞 `knowledge_entries/knowledge_{task_id}.json` **淇濇寔鍘熸湁鏍煎紡涓嶅彉**

### 10.2 涓?knowledge.db 鐨勫叧绯伙紙褰撳墠涓嶅瓨鍦級

knowledge.db锛圫QLite锛夊綋鍓?*涓嶅瓨鍦?*锛屾湰椤圭洰涓嶆秹鍙?SQLite 鐭ヨ瘑搴撳缓璁俱€?BitableSync 鐩存帴娑堣垂 knowledge_entries JSON 鏂囦欢浣滀负鍞竴鏁版嵁婧愩€?
### 10.3 鏂囦欢鐩綍寤鸿

```
src/backtest/
鈹溾攢鈹€ engine/
鈹?  鈹溾攢鈹€ knowledge_bridge.py        鈫?淇濈暀锛坔arvest 鏂规硶锛屾寜 import 浣跨敤锛?鈹?  鈹斺攢鈹€ knowledge_bridge_v2.py     鈫?鏂板锛坴2 鍗忚 + Normalizer锛屼粠闆跺垱寤猴級
鈹溾攢鈹€ sync/
鈹?  鈹溾攢鈹€ bitable_sync.py            鈫?鏂板锛圔itable 鍚屾鍣級
鈹?  鈹斺攢鈹€ bitable_sync_test.py       鈫?鏂板锛堝悓姝ュ櫒娴嬭瘯锛?鈹溾攢鈹€ knowledge_entries/             鈫?淇濈暀锛圝SON 鏂囦欢瀛樺偍锛?鈹溾攢鈹€ pipeline/
鈹?  鈹斺攢鈹€ knowledge_extractor.py     鈫?淇濈暀
scripts/
鈹斺攢鈹€ backfill_bitable.py            鈫?鏂板锛圔itable 鍥炲～锛?```

### 10.4 `.done` Signal 鍏煎

BitableSync 鐨勫悓姝ョ粨鏋滈€氳繃鐜版湁 Signal 鏈哄埗璁板綍锛?
```json
// signals/tasks/{task_id}_bitable_sync.done
{
  "task_id": "sync_morning_20260517",
  "agent": "moheng",
  "timestamp": "2026-05-17T12:30:00+08:00",
  "status": "SUCCESS",
  "summary": "Bitable sync completed: 12 synced, 2 skipped, 0 failed"
}
```

---

## 11. 闄勫綍

### A. 鍙傝€冩枃妗?
| 鏂囨。 | 鏂囦欢 |
|:-----|:------|
| 鎻掍欢绯荤粺鏈€缁堣璁?v1.4锛埪? KnowledgeBridge锛墊 `docs/01_architecture/plugin_system_final_design_20260517.md` |
| 鍥炴祴鐭ヨ瘑搴撶郴缁熻璁?v2.2 | `docs/02_development/knowledge_db_design.md` |
| 鐭ヨ瘑鍙嶉寰幆璁捐 v1.0 | `docs/02_development/knowledge_feedback_loop_design.md` |
| KnowledgeBridge 瀹炵幇 | `src/backtest/engine/knowledge_bridge.py` |

### B. 椋炰功 Bitable API 鍙傝€?
- 鍒涘缓璁板綍: `POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`
- 鏇存柊璁板綍: `PUT /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}`
- 鏌ヨ璁板綍: `GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`
- 鍒楀嚭瀛楁: `GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields`

### C. 鏂囦欢鐗堟湰璁板綍

| 鐗堟湰 | 鏃ユ湡 | 鍙樻洿 | 浣滆€?|
|:-----|:-----|:------|:-----|
| v1.0 | 2026-05-17 | 鍒濈増锛?灞傛灦鏋?+ v2鍗忚 + Normalizer + BitableSync + 3Phase | 澧ㄨ　 |
| v2.0 | 2026-05-17 | 淇4椤癸細鈶?鍘绘帀v1淇濈暀涓嶅姩鍓嶆彁 鈫?浠庨浂鍒涘缓锛涒憽 Phase 3 鍒犻櫎AI鎽樿 鈫?缁熻妯℃澘鍖栵紱鈶?Phase 1 鎷?瀛愰樁娈碉紱鈶?鏍囨敞Bitable鏉冮檺缂哄彛锛涙€诲伐鏈?2d鈫?7d | 澧ㄨ　 |

---

*鏈枃鍩轰簬澧ㄦ兜 PO 鍓嶇鏂规 + 涓讳汉璇勫琛ュ厖 + 鐜版湁 KnowledgeBridge/KnowledgeDB 瀹炵幇缂栧啓銆?
*鏍稿績鍘熷垯锛歅hase 1 鍏堝仛缁撴瀯鍖栫煡璇?+ Bitable 鍙锛屼笉鎬?AI銆?

