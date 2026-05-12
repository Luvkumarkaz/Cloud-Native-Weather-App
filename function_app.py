import datetime
import json
import urllib.request
import os
import logging
import time
import azure.functions as func
from azure.storage.blob import BlobServiceClient

# Initialize the Azure Function App
app = func.FunctionApp()

# The cron schedule "0 0 0 * * *" runs exactly at midnight
@app.timer_trigger(schedule="0 0 0 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False) 
def daily_weather_ingestion(mytimer: func.TimerRequest) -> None:
    # 1. Define the API endpoint (New Delhi coordinates)
    url = "https://api.open-meteo.com/v1/forecast?latitude=28.6139&longitude=77.2090&current_weather=true"

    try:
        logging.info("Fetching daily weather data...")
        response = urllib.request.urlopen(url)
        raw_data = response.read().decode('utf-8')
        json_data = json.loads(raw_data)

        # 2. Create a unique filename
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"weather_data_{timestamp}.json"

        # 3. Connect to the Data Lake using the hidden environment variable
        connection_string = os.environ["AzureWebJobsStorage"]
        container_name = "raw-data-zone"

        # 4. Upload the file
        logging.info(f"Uploading {file_name} to Azure Data Lake...")
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=file_name)

        blob_client.upload_blob(json.dumps(json_data), overwrite=True)
        logging.info("Ingestion successful!")

    except Exception as e:
        logging.error(f"ETL Extraction Error: {str(e)}")

# ... (Keep your existing timer function above) ...

import pymssql

@app.event_grid_trigger(arg_name="event")
def transform_weather_data(event: func.EventGridEvent):
    logging.info(f"Event Grid woke up the worker for: {event.subject}")

    # 1. Extract the container and file name from the Event Grid notification
    # The subject always looks like: /blobServices/default/containers/raw-data-zone/blobs/filename.json
    parts = event.subject.split('/')
    if len(parts) < 7:
        logging.error("Could not parse file path from event.")
        return
        
    container_name = parts[4]
    blob_name = "/".join(parts[6:])

    # 2. Connect to the Storage Account and download the file
    try:
        connection_string = os.environ.get("DataStorageConn")
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        
        # Read the JSON
        # 1. Parse the JSON
        blob_data = json.loads(blob_client.download_blob().readall().decode('utf-8'))
        
        # Based on your JSON, the key is 'current_weather'
        current = blob_data.get('current_weather', {})
        
        # Exact keys from your file: temperature, windspeed, winddirection, weathercode
        temp = current.get('temperature', 0)
        w_speed = current.get('windspeed', 0)
        w_dir = current.get('winddirection', 0)
        w_code = current.get('weathercode', 0)
        
        # Get times for your logDate and ObservationTime columns
        now = datetime.datetime.now()
        log_date = now.strftime('%Y-%m-%d')
        obs_time = now.strftime('%H:%M:%S')

        logging.info(f"Mapped Open-Meteo -> Temp: {temp}, Wind: {w_speed}")
        
    except Exception as e:
        logging.error(f"Storage Download Error: {e}")
        return

    # 3. Connect to SQL and Insert (Exactly the same as before)
    server = os.environ.get('SQL_SERVER') 
    database = os.environ.get('SQL_DATABASE')
    username = os.environ.get('SQL_USER')
    password = os.environ.get('SQL_PASSWORD')

    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn = pymssql.connect(server=server, user=username, password=password, database=database)
            cursor = conn.cursor()
            
            query = """
                INSERT INTO DailyWeather (logDate, ObservationTime, Temperature, WindSpeed, WindDirection, WeatherCode) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (log_date, obs_time, temp, w_speed, w_dir, w_code))
            conn.commit()
            logging.info(f"Successfully inserted into SQL Database on attempt {attempt + 1}!")
            break # Success! Exit the loop.
        except Exception as e:
            # If it's a connection error (like 40613), wait and retry
            if "40613" in str(e) and attempt < max_retries - 1:
                logging.warning(f"Database is waking up... retrying in 30s (Attempt {attempt + 1})")
                time.sleep(30) # Wait for the serverless DB to resume
            else:
                logging.error(f"SQL Connection/Insert Error: {e}")
                break
        finally:
            if 'conn' in locals():
                conn.close()