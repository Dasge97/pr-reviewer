cd "C:\Users\Practicas 2025\Desktop\DANIEL\pr-revisor"
.\.venv\Scripts\Activate.ps1
Get-Content .env.local

cd "C:\Users\Practicas 2025\Desktop\DANIEL\pr-revisor"
.\scripts\start-local.ps1

cloudflared tunnel --url http://127.0.0.1:8001

Invoke-RestMethod http://127.0.0.1:8001/healthz

cd "C:\Users\Practicas 2025\Desktop\SANDBOX\todo-minimo"
git checkout implementacion_simple
Add-Content .\README.md "`nSmoke test $(Get-Date -Format s)"
git add README.md
git commit -m "test: retrigger webhook"
git push
