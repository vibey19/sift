import numpy
import pandas
import sklearn
from fastapi import FastAPI

app = FastAPI(title="Sift", docs_url=None, redoc_url=None)


# Routes carry the full /api prefix because vercel.json rewrites /api/(.*) to this
# function without stripping the original path.
@app.get("/api/health")
def health() -> dict:
    # The versions are here so a deploy proves the analytical stack actually
    # imported inside the function, not just that the function booted.
    return {
        "ok": True,
        "versions": {
            "pandas": pandas.__version__,
            "numpy": numpy.__version__,
            "sklearn": sklearn.__version__,
        },
    }
