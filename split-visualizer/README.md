# Nginx split_clients visualizer

一個公開網站,讓任何人送出真實的 request、修改 `split_clients` 設定,並看到 Nginx 實際怎麼分流。

```
Browser (Vercel 靜態頁)
   │  HTTPS
   ▼
Legacy Nginx (front door, $PORT) ──split_clients──► Legacy Nginx 自己 (127.0.0.1:8080)
                                 └────────────────► New Nginx (127.0.0.1:8082,獨立 process)
```

- `backend/`:一個 Docker image,裡面跑**兩個真的 Nginx process**(Legacy 與 New)和一個小的 control API(`control.py`,只用 Python 標準函式庫)。部署到 Render。
- `web/`:純靜態前端(HTML / CSS / JS,不需要 build)。部署到 Vercel。

訪客只能改 `split_clients` 區塊與 `X-Canary` map。control API 只接受白名單內的 split key 與 upstream 名稱,寫入後先跑 `nginx -t`,通過才 reload。config 是所有訪客共用的,後寫的會覆蓋先寫的;container 重啟後回到預設值。

## 本機執行

```bash
docker build -t split-demo split-visualizer/backend
```

```bash
docker run --rm -p 10000:10000 split-demo
```

```bash
python3 -m http.server 5173 --directory split-visualizer/web
```

打開 http://localhost:5173 。在 localhost 上前端會自動連 `http://localhost:10000`。

## 部署

先把程式碼 commit 並 push 到 GitHub,Render 與 Vercel 都是從 GitHub repo 部署。

### 1. 後端 → Render

1. 到 https://render.com 用 GitHub 帳號登入。
2. **New → Web Service**,選這個 repo 與要部署的 branch。
3. 設定:
   - **Language / Runtime**:Docker
   - **Root Directory**:`split-visualizer/backend`
   - **Instance Type**:Free
   - **Health Check Path**:`/healthz`
4. 按 **Deploy**,等到狀態變成 Live。
5. 記下服務網址,例如 `https://nginx-split-demo.onrender.com`。
6. 驗證:瀏覽器打開 `<服務網址>/hit`,應該看到 `{"served_by":"new_nginx",...}` 或 `legacy_nginx`,多重新整理幾次會兩邊都出現。

也可以改用 repo 根目錄的 `render.yaml`(**New → Blueprint**),它描述的是同一組設定。

### 2. 前端 → Vercel

1. 編輯 `web/config.js`,填入上一步的 Render 網址(結尾不要加 `/`):

   ```js
   window.SPLIT_BACKEND_URL = "https://nginx-split-demo.onrender.com";
   ```

2. commit 並 push。
3. 到 https://vercel.com 用 GitHub 帳號登入,**Add New → Project**,匯入這個 repo。
4. 設定:
   - **Root Directory**:`split-visualizer/web`
   - **Framework Preset**:Other
   - Build Command 與 Output Directory 留空
5. 按 **Deploy**。完成後打開 Vercel 給的網址即可。

之後每次 push,Render 與 Vercel 都會自動重新部署。

## 免費方案的限制

- Render 免費服務 15 分鐘沒有流量會休眠,下一位訪客要等大約 1 分鐘喚醒,頁面會顯示 "Waking Nginx…"。
- 休眠或重新部署後 config 會回到預設值。
- 免費額度可能調整,部署前請以 Render 官方定價頁為準。

## Control API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/state` | 目前設定、兩份 nginx.conf、New Nginx 是否在跑 |
| POST | `/api/config` | 套用新的 split 設定(`nginx -t` 後 reload) |
| POST | `/api/reset` | 還原預設值 |
| POST | `/api/new-nginx` | `{"up": false}` 停掉 New Nginx(120 秒後自動啟動),用來示範 fallback |
| GET | `/api/trace?id=<request id>` | 兩個 Nginx 的 access log 中屬於該 request 的紀錄 |
| GET | `/hit` | 被分流的 request,回應 header 帶有 Nginx 的分流結果 |
