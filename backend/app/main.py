from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints import (
    auth, assets, billings, capital, contracts, dashboard, excel, files, health, invoices, leasing, master, ocr, orders,
    projects, repayments, reports,
)

app = FastAPI(title="SIEGPU ERP", version="2.0")

app.add_middleware(
    CORSMiddleware,
    # W5：收敛白名单 + 关闭 credentials（鉴权用 Bearer，不用 cookie）
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def _integrity_handler(request: Request, exc: IntegrityError):
    # W11：DB 约束冲突统一映射 409，不回原始 SQL（防泄漏）
    return JSONResponse(
        status_code=409,
        content={"code": "INTEGRITY_ERROR", "message": "数据约束冲突（唯一/检查/外键）"},
    )


@app.get("/")
def root():
    return {"name": "SIEGPU ERP", "version": "2.0", "docs": "/docs"}


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(capital.router, prefix="/api/capital", tags=["capital"])
app.include_router(leasing.router, prefix="/api/leasing", tags=["leasing"])
app.include_router(master.suppliers_router, prefix="/api/suppliers", tags=["master"])
app.include_router(master.customers_router, prefix="/api/customers", tags=["master"])
app.include_router(master.equipment_models_router, prefix="/api/equipment-models", tags=["master"])
app.include_router(master.banks_router, prefix="/api/banks", tags=["master"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(billings.router, prefix="/api/billings", tags=["billings"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
app.include_router(repayments.router, prefix="/api/repayments", tags=["repayments"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(excel.router, prefix="/api/excel", tags=["excel"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(ocr.router, prefix="/api/ocr", tags=["ocr"])
