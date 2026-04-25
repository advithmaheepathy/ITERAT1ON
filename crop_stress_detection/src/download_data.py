"""
download_data.py
================
Downloads real Sentinel-2 L2A data from Copernicus Data Space.

TWO METHODS:
  Method A: sentinelsat (Copernicus OpenSearch API)
  Method B: OData REST API (no extra library needed)

USAGE:
  python src/download_data.py \
      --method sentinelsat \
      --aoi data/aoi.geojson \
      --start 2024-06-01 \
      --end 2024-09-30 \
      --cloud_max 20 \
      --output_dir data/raw

CREDENTIALS:
  Set environment variables:
    export COPERNICUS_USER="your_username"
    export COPERNICUS_PASS="your_password"
  Register free at: https://dataspace.copernicus.eu/

AOI FILE FORMAT (data/aoi.geojson):
  {
    "type": "Polygon",
    "coordinates": [[[lon1,lat1], [lon2,lat2], ...]]
  }
  Use https://geojson.io to draw your field boundary.
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logger = logging.getLogger(__name__)


def load_aoi(aoi_path: str) -> dict:
    """Load AOI from GeoJSON file. Returns geometry dict."""
    with open(aoi_path) as f:
        geojson = json.load(f)
    
    # Handle both FeatureCollection and bare Geometry
    if geojson.get("type") == "FeatureCollection":
        geometry = geojson["features"][0]["geometry"]
    elif geojson.get("type") == "Feature":
        geometry = geojson["geometry"]
    else:
        geometry = geojson  # bare Polygon/MultiPolygon
    
    logger.info(f"AOI loaded: {geometry['type']}")
    return geometry


def download_sentinelsat(
    aoi_geometry: dict,
    start_date: str,
    end_date: str,
    cloud_max: int,
    output_dir: str,
    username: str,
    password: str,
):
    """
    Download Sentinel-2 L2A products using sentinelsat library.
    
    sentinelsat docs: https://sentinelsat.readthedocs.io/
    """
    try:
        from sentinelsat import SentinelAPI, geojson_to_wkt, read_geojson
    except ImportError:
        logger.error("sentinelsat not installed. Run: pip install sentinelsat==1.2.1")
        sys.exit(1)
    
    from shapely.geometry import shape
    
    api = SentinelAPI(
        username,
        password,
        "https://apihub.copernicus.eu/apihub"
    )
    
    # Convert GeoJSON geometry to WKT for API query
    footprint = shape(aoi_geometry).wkt
    
    logger.info(f"Querying Sentinel-2 L2A: {start_date} to {end_date}, cloud<{cloud_max}%")
    
    products = api.query(
        area=footprint,
        date=(
            datetime.strptime(start_date, "%Y-%m-%d"),
            datetime.strptime(end_date, "%Y-%m-%d")
        ),
        platformname="Sentinel-2",
        producttype="S2MSI2A",
        cloudcoverpercentage=(0, cloud_max)
    )
    
    logger.info(f"Found {len(products)} products matching criteria")
    
    if len(products) == 0:
        logger.warning("No products found. Try widening date range or cloud threshold.")
        return
    
    # Log product details before download
    for pid, pinfo in products.items():
        logger.info(
            f"  {pinfo['title']} | "
            f"Date: {pinfo['beginposition'].strftime('%Y-%m-%d')} | "
            f"Cloud: {pinfo['cloudcoverpercentage']:.1f}%"
        )
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Download all found products
    api.download_all(products, directory_path=str(output_path))
    
    logger.info(f"Downloads complete. Unzip .zip files in {output_dir}")
    logger.info("Expected structure: S2*_MSIL2A_*.SAFE/GRANULE/*/IMG_DATA/R10m/*.tif")


def download_odata_api(
    aoi_geometry: dict,
    start_date: str,
    end_date: str,
    cloud_max: int,
    output_dir: str,
    username: str,
    password: str,
):
    """
    Download via Copernicus OData REST API.
    No sentinelsat required — uses requests only.
    
    API docs: https://documentation.dataspace.copernicus.eu/APIs/OData.html
    """
    import requests
    from shapely.geometry import shape
    
    # Get access token
    token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    token_resp = requests.post(
        token_url,
        data={
            "client_id": "cdse-public",
            "username": username,
            "password": password,
            "grant_type": "password"
        }
    )
    token_resp.raise_for_status()
    access_token = token_resp.json()["access_token"]
    
    # Build geometry filter (WKT)
    footprint_wkt = shape(aoi_geometry).wkt
    
    # Query OData API
    base_url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    filter_str = (
        f"Collection/Name eq 'SENTINEL-2' and "
        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
        f"and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"ContentDate/Start gt {start_date}T00:00:00.000Z and "
        f"ContentDate/Start lt {end_date}T23:59:59.000Z and "
        f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
        f"and att/OData.CSC.DoubleAttribute/Value le {cloud_max}.00) and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{footprint_wkt}')"
    )
    
    resp = requests.get(
        base_url,
        params={"$filter": filter_str, "$top": 20, "$orderby": "ContentDate/Start desc"},
        headers={"Authorization": f"Bearer {access_token}"}
    )
    resp.raise_for_status()
    products = resp.json()["value"]
    
    logger.info(f"Found {len(products)} products via OData API")
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for i, product in enumerate(products, 1):
        product_id = product["Id"]
        product_name = product["Name"]
        logger.info(f"[{i}/{len(products)}] Downloading: {product_name}")
        
        # Use zipper service for download (more reliable)
        download_url = f"https://zipper.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"
        
        out_file = output_path / f"{product_name}.zip"
        
        try:
            with requests.get(
                download_url,
                headers={"Authorization": f"Bearer {access_token}"},
                stream=True,
                timeout=300
            ) as r:
                r.raise_for_status()
                
                # Get file size if available
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                
                with open(out_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = (downloaded / total_size) * 100
                                logger.info(f"  Progress: {pct:.1f}% ({downloaded/(1024**2):.1f}MB / {total_size/(1024**2):.1f}MB)")
            
            logger.info(f"✓ Saved: {out_file} ({out_file.stat().st_size/(1024**2):.1f}MB)")
        except Exception as e:
            logger.error(f"✗ Failed to download {product_name}: {e}")
            if out_file.exists():
                out_file.unlink()  # Remove partial download
            continue
    
    logger.info(f"\nDownload complete. Unzip contents into {output_dir}/")
    logger.info("Then run: python src/run_pipeline.py --safe_dir data/raw/")


def main():
    parser = argparse.ArgumentParser(description="Download Sentinel-2 L2A data")
    parser.add_argument("--method", choices=["sentinelsat", "odata"], default="odata")
    parser.add_argument("--aoi", required=True, help="Path to AOI GeoJSON file")
    parser.add_argument("--start", default="2024-06-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2024-09-30", help="End date YYYY-MM-DD")
    parser.add_argument("--cloud_max", type=int, default=20)
    parser.add_argument("--output_dir", default="data/raw")
    args = parser.parse_args()
    
    username = os.environ.get("COPERNICUS_USER")
    password = os.environ.get("COPERNICUS_PASS")
    
    if not username or not password:
        logger.error(
            "Credentials not set. Run:\n"
            "  export COPERNICUS_USER='your_username'\n"
            "  export COPERNICUS_PASS='your_password'\n"
            "Register free at: https://dataspace.copernicus.eu/"
        )
        sys.exit(1)
    
    aoi = load_aoi(args.aoi)
    
    if args.method == "sentinelsat":
        download_sentinelsat(aoi, args.start, args.end, args.cloud_max,
                             args.output_dir, username, password)
    else:
        download_odata_api(aoi, args.start, args.end, args.cloud_max,
                           args.output_dir, username, password)


if __name__ == "__main__":
    main()