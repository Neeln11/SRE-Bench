import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import uvicorn

def main():
    uvicorn.run("main:app", host="0.0.0.0", port=7860, workers=1)

if __name__ == "__main__":
    main()
