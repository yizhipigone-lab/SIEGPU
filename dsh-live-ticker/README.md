# dsh-live-ticker

DSH 鎻掍欢锛氬璇濇搴曢儴锛堣緭鍏ユ鍗＄墖涓嬫柟锛変袱涓彲鎶樺彔琛屸€斺€? 涓寚鏁板疄鏃惰鎯?+ 涓滆储璐㈢粡鏂伴椈婊氬姩銆?
## 鏁版嵁婧?- 鎸囨暟锛氫笢鏂硅储瀵?push2锛堟祻瑙堝櫒鐩磋繛锛孋ORS `*`锛夛紝5s 杞銆備笂璇佹寚鏁?/ 鍒涗笟鏉挎寚 / 绉戝垱50 / 涓瘉A500锛坄1.000510`锛夈€?- 鏂伴椈锛氫笢鏂硅储瀵屾柊闂诲垪琛紙host 浠ｇ悊锛屽悓婧?`/live-ticker/news`锛?0s 缂撳瓨锛夛紝60s 杞銆?
## 瀹夎
```sh
dsh plugin --profile web add "file:E:/1target/SIEGPU/dsh-live-ticker"
# 閲嶅惎 dsh --profile web
```

## 鍗歌浇
```sh
dsh plugin --profile web remove dsh-live-ticker
```

## 寮€鍙?- host锛歚src/index.ts`锛坱sx 鍔犺浇锛?- client锛歚src/client/` 鈫?`node scripts/build-client.mjs` 鈫?`lib/client.js`
- 娴嬭瘯锛歚node --test "tests/**/*.test.mjs"`

