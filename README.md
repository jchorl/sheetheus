# Sheetheus
## What?
It scrapes google sheets and gets data into prometheus

## Running Locally
```
docker run -it --rm \
    -e RO_FILESYSTEM=1 \
    -e FINANCE_SPREADSHEET_ID=1yiHbSLDIIYPZPJrgfSnpJZKelaQ3CFVE9bFPs77MMAI \
    -e CRED_PATH=/work/token.pickle \
    -v $(pwd):/work \
    -w /work \
    python:3 bash
```
