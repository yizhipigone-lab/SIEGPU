# dsh-live-ticker

DSH 插件：对话框底部（输入框卡片下方）两个可折叠行——4 个指数实时行情 + 东财财经新闻滚动。

## 数据源
- 指数：东方财富 push2（浏览器直连，CORS `*`），5s 轮询。上证指数 / 创业板指 / 科创50 / 中证A500（`1.000510`）。
- 新闻：东方财富新闻列表（host 代理，同源 `/live-ticker/news`，30s 缓存），60s 轮询。

## 安装
```sh
dsh plugin --profile web add "file:E:/1target/SIEGPU/dsh-live-ticker"
# 重启 dsh --profile web
```

## 卸载
```sh
dsh plugin --profile web remove dsh-live-ticker
```

## 开发
- host：`src/index.ts`（tsx 加载）
- client：`src/client/` → `node scripts/build-client.mjs` → `lib/client.js`
- 测试：`node --test tests/`
