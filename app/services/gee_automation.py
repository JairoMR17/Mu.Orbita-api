#!/usr/bin/env python3
"""
Mu.Orbita GEE Automation Script v3
"""
import argparse
import json
import ee
import sys
import os
from datetime import datetime, timedelta

def initialize_gee():
    try:
        service_account_key = os.environ.get('GEE_SERVICE_ACCOUNT_KEY')
        if service_account_key:
            key_data = json.loads(service_account_key)
            credentials = ee.ServiceAccountCredentials(
                email=key_data['client_email'],
                key_data=service_account_key
            )
            ee.Initialize(credentials)
        else:
            ee.Initialize()
        return True
    except Exception as e:
        print(json.dumps({"error": f"Failed to initialize GEE: {str(e)}"}))
        return False

if not initialize_gee():
    sys.exit(1)

