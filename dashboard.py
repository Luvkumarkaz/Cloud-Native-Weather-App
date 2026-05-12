import streamlit as st
import pandas as pd
import pymssql
import os
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()

# Set page config for a "Tech" look
st.set_page_config(page_title="Delhi Weather ETL", page_icon="🌤️", layout="wide")

st.title("Delhi Real-Time Weather Dashboard")
st.markdown("**Data Pipeline:** Open-Meteo API → Azure Data Lake → Event Grid → Azure Function → Azure SQL")
st.divider()

# Dictionary to map Open-Meteo codes to human-readable statuses
WEATHER_CODES = {
    0: "☀️ Clear sky",
    1: "🌤️ Mainly clear",
    2: "⛅ Partly cloudy",
    3: "☁️ Overcast",
    45: "🌫️ Fog",
    48: "🌫️ Depositing rime fog",
    51: "🌧️ Light drizzle",
    53: "🌧️ Moderate drizzle",
    55: "🌧️ Dense drizzle",
    61: "🌧️ Slight rain",
    63: "🌧️ Moderate rain",
    65: "🌧️ Heavy rain",
    80: "🌦️ Slight rain showers"
}

# 1. Database Connection Function
@st.cache_data(ttl=60) # Caches data for 60 seconds so it doesn't query SQL on every button click
def get_data():
    server = os.environ.get('SQL_SERVER')
    database = os.environ.get('SQL_DATABASE')
    username = os.environ.get('SQL_USER')
    password = os.environ.get('SQL_PASSWORD')
    
    conn = pymssql.connect(server=server, user=username, password=password, database=database)
    # Order descending to easily grab the latest, but we will sort ascending for charts
    query = "SELECT logDate, ObservationTime, Temperature, WindSpeed, WindDirection, WeatherCode FROM DailyWeather ORDER BY logDate DESC, ObservationTime DESC"
    df = pd.read_sql(query, conn)
    conn.close()
    return df

# 2. Fetch and Display Data
try:
    df = get_data()

    if df.empty:
        st.warning("📡 The database is currently empty. Waiting for the Azure ingestion trigger...")
    else:
        # Prepare Data
        df['DateTime'] = pd.to_datetime(df['logDate'].astype(str) + ' ' + df['ObservationTime'].astype(str))
        
        # Sort chronologically (oldest to newest) so the charts draw left-to-right correctly
        df_charts = df.sort_values(by='DateTime')

        # Grab latest and previous records for the "Delta" arrows
        latest = df.iloc[0]
        previous = df.iloc[1] if len(df) > 1 else latest

        # Map weather code to string, default to "Unknown" if code isn't in dictionary
        current_weather_desc = WEATHER_CODES.get(int(latest['WeatherCode']), f"Code: {int(latest['WeatherCode'])}")

        # --- TOP ROW: KPI METRICS ---
        st.subheader("Current Conditions")
        col1, col2, col3 = st.columns(3)
        
        # Calculate changes for the delta arrows
        temp_change = round(latest['Temperature'] - previous['Temperature'], 1)
        wind_change = round(latest['WindSpeed'] - previous['WindSpeed'], 1)

        col1.metric("Temperature", f"{latest['Temperature']}°C", f"{temp_change}°C")
        col2.metric("Wind Speed", f"{latest['WindSpeed']} km/h", f"{wind_change} km/h")
        col3.metric("Weather Status", current_weather_desc)

        st.write("") # Spacer

        # --- MIDDLE ROW: INTERACTIVE CHARTS ---
        # Using tabs keeps the UI clean
        tab1, tab2, tab3 = st.tabs(["📈 Temperature Trends", "💨 Wind Analytics", "🗄️ Raw Data"])

        with tab1:
            st.markdown("### Temperature Over Time")
            # Plotly Line Chart
            fig_temp = px.line(
                df_charts, 
                x='DateTime', 
                y='Temperature', 
                markers=True,
                color_discrete_sequence=['#FF4B4B'] # Streamlit red
            )
            fig_temp.update_layout(xaxis_title="Time", yaxis_title="Temperature (°C)")
            st.plotly_chart(fig_temp, use_container_width=True)

        with tab2:
            st.markdown("### Wind Speed Intensity")
            # Plotly Bar Chart with color scaling
            fig_wind = px.bar(
                df_charts, 
                x='DateTime', 
                y='WindSpeed',
                color='WindSpeed',
                color_continuous_scale='Blues'
            )
            fig_wind.update_layout(xaxis_title="Time", yaxis_title="Wind Speed (km/h)")
            st.plotly_chart(fig_wind, use_container_width=True)

        with tab3:
            st.markdown("### Database Records")
            # Show the raw dataframe
            st.dataframe(df.drop(columns=['DateTime']), use_container_width=True)

except Exception as e:
    st.error(f"Failed to connect to the data source. Error: {e}")