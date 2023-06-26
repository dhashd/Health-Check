import streamlit as st
import telnetlib
import requests
import plotly.graph_objects as go
import pandas as pd
import time
import threading
import json
from kafka import KafkaProducer
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from pythonping import ping

# Thông tin kết nối Kafka
conf = {
    'bootstrap_servers': '103.88.122.142:9092',
    'acks': 'all',
    'retries': 3,
    'compression_type': 'gzip',
    'linger_ms': 5
}

# Khởi tạo Kafka producer
producer = KafkaProducer(**conf)

# Khởi tạo topic
topic = 'health_check'

# Biến cờ để theo dõi trạng thái của việc gửi message đến Kafka
is_running_kafka = True

# Gửi message đến kafka topic
producer.send(topic=topic, value=json.dumps("v").encode('utf-8'))


# Thông tin kết nối InfluxDB
url = "http://103.88.122.142:8086"
token = "8kGaTZ1CJKLv2go70bVIrL4yBPJnPaJvao8AtHHhLKji5uonRZ4wFQX6P7-X-KxfqSnfJSp7wm5rP-IXDHuC1g=="
org = "4777df723b06332f"
bucket = "1"

# Khởi tạo kết nối InfluxDB
client = InfluxDBClient(url=url, token=token)

# Biến cờ để theo dõi trạng thái của việc thực hiện health check tự động
is_running = True

# Hàm gửi dữ liệu lên InfluxDB
def send_to_influxdb(measurement, tags, fields):
    client = InfluxDBClient(url=url, token=token, org=org)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    point = Point(measurement)
    for key, value in tags.items():
        point.tag(key, value)
    for key, value in fields.items():
        point.field(key, value)
        
    write_api.write(bucket=bucket, record=point)
    client.close()

# Hàm gửi thông báo discord
discord_webhook_url = 'https://discordapp.com/api/webhooks/1122465754114166806/ROQoicax-l2JdzC3gy1FeDmphnBqpPZHgQLTnjLYBj_Za6q-UJ2DFBrTUDQNQAAFNjIj'

def send_discord_notification(message):
    data = {
        'content': message
    }
    response = requests.post(discord_webhook_url, data=json.dumps(data), headers={'Content-Type': 'application/json'})
    if response.status_code != 204:
        print('Failed to send Discord notification.')

previous_statuses = {}

def check_and_notify_status(status_key, current_status, success_message, failure_message):
    global previous_statuses
    
    previous_status = previous_statuses.get(status_key)
    
    if current_status != previous_status:
        if current_status == '1':
            send_discord_notification(failure_message)
        elif current_status == '2':
            send_discord_notification(success_message)
        
        previous_statuses[status_key] = current_status

previous_http_statuses = {}
previous_https_statuses = {}

def check_and_notify_http_status(url, current_status):
    global previous_http_statuses
    
    previous_status = previous_http_statuses.get(url)
    
    if current_status != previous_status:
        if current_status == '1':
            send_discord_notification(f'HTTP request to {url} failed. Status code: {response.status_code}')
        elif current_status == '2':
            send_discord_notification(f'HTTP request to {url} successful.')
        
        previous_http_statuses[url] = current_status

def check_and_notify_https_status(url, current_status):
    global previous_https_statuses
    
    previous_status = previous_https_statuses.get(url)
    
    if current_status != previous_status:
        if current_status == '1':
            send_discord_notification(f'HTTPS request to {url} failed. Status code: {response.status_code}')
        elif current_status == '2':
            send_discord_notification(f'HTTPS request to {url} successful.')
        
        previous_https_statuses[url] = current_status

def ping_ip(address):
    try:
        response_list = ping(address, count=1)
        if response_list.success():
            current_status = '2'
        else:
            current_status = '1'
        
        check_and_notify_status(
            f'ping_{address}',
            current_status,
            f'Ping to {address} successful.',
            f'Ping to {address} failed.'
        )
        
        tags = {'address': address}
        fields = {'status': current_status}
        send_to_influxdb('ping', tags, fields)
        
        if current_status == '2':
            st.write(f'Ping to {address} :green[successful]')
        else: 
            st.write(f'Ping to {address} :red[failed]')
    except Exception as e:
        st.write(f'Ping to {address} :red[failed] {str(e)}')

def telnet_ip(address, port):
    try:
        tn = telnetlib.Telnet(address, port, timeout=3)
        tn.close()
        current_status = '2'
        st.write(f'Telnet to {address}:{port}: :green[successful]')
    except ConnectionRefusedError:
        current_status = '1'
        st.write(f'Telnet to {address}:{port}: :red[failed] Connection refused.')
    except TimeoutError:
        current_status = '1'
        st.write(f'Telnet to {address}:{port}: :red[failed] Connection timeout.')
    except Exception as e:
        current_status = '1'
        st.write(f'Telnet to {address}:{port}: :red[failed] {str(e)}')
    finally:
        check_and_notify_status(
            f'telnet_{address}_{port}',
            current_status,
            f'Telnet to {address}:{port} successful.', 
            f'Telnet to {address}:{port} failed.' 
        )
        
        tags = {'address': address, 'port': port}
        fields = {'status': current_status}
        send_to_influxdb('telnet', tags, fields)

def http_request(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            current_status = '2'
            st.write(f'HTTP request to {url}: :green[successful]')
        else:
            current_status = '1'
            st.write(f'HTTP request to {url}: :red[failed] Status code: {response.status_code}')
    except requests.exceptions.RequestException as e:
        current_status = '1'
        st.write(f'HTTP request to {url}: :red[failed] {str(e)}')
    
    check_and_notify_http_status(url, current_status)
    
    tags = {'url': url}
    fields = {'status': current_status}
    send_to_influxdb('http', tags, fields)

def https_request(url):
    try:
        response = requests.get(url, verify=True)
        if response.status_code == 200:
            current_status = '2'
            st.write(f'HTTPS request to {url}: :green[successful]')
        else:
            current_status = '1'
            st.write(f'HTTPS request to {url}: :red[failed] Status code: {response.status_code}')
    except requests.exceptions.RequestException as e:
        current_status = '1'
        st.write(f'HTTPS request to {url}: :red[failed] {str(e)}')
    
    check_and_notify_https_status(url, current_status)
    
    tags = {'url': url}
    fields = {'status': current_status}
    send_to_influxdb('https', tags, fields)

# Hàm thực hiện công việc tự động
def perform_auto_check(check_type, ip_address=None, port=None, url=None, interval=5):

    # Biến cờ để theo dõi trạng thái của việc thực hiện health check tự động
    is_running = True
    while is_running and is_running_kafka:
        if check_type == "Ping":
            ping_ip(ip_address)
        elif check_type == "Telnet":
            telnet_ip(ip_address, port)
        elif check_type == "HTTP":
            http_request(url)
        elif check_type == "HTTPS":
            https_request(url)
        time.sleep(interval)

def ping_telnet_page():
    st.title("🚀 Ping & Telnet")

    # Địa chỉ IP để ping
    ip_address = st.text_input("Nhập địa chỉ IP:")

    # Cổng để telnet
    port = st.text_input("Nhập cổng telnet:")

    # Kiểm tra nút Start được nhấn hay không
    if st.button("Start"):
        # Kiểm tra xem địa chỉ IP và cổng có được nhập hay không
        if ip_address:
            st.write("Đang ping địa chỉ IP:", ip_address)
            result_ping = ping_ip(ip_address)
            st.write(result_ping)

        if port:
            st.write("Đang thực hiện telnet tới địa chỉ IP và cổng:", ip_address, port)
            result_telnet = telnet_ip(ip_address, port)
            st.write(result_telnet)

def http_https_page():
    st.title("📡 HTTP & HTTPS")

    # URL để thực hiện HTTP request
    http_url = st.text_input("Nhập URL HTTP:")

    # URL để thực hiện HTTPS request
    https_url = st.text_input("Nhập URL HTTPS:")

    # Kiểm tra nút Start được nhấn hay không
    if st.button("Start"):
        if http_url:
            st.write("Đang thực hiện HTTP request tới URL:", http_url)
            result_http = http_request(http_url)
            st.write(result_http)

        if https_url:
            st.write("Đang thực hiện HTTPS request tới URL:", https_url)
            result_https = https_request(https_url)
            st.write(result_https)

def event_log_page():
    st.title("🚝 Event Log")

    # Chọn measurement để truy xuất dữ liệu
    selected_measurement = st.selectbox("Chọn measurement:", ["ping", "telnet", "http", "https"], key="event_log_measurement")

    # Kết nối tới InfluxDB
    client = InfluxDBClient(url=url, token=token)

    # Truy vấn dữ liệu từ InfluxDB
    query = f'from(bucket: "{bucket}") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "{selected_measurement}")'
    tables = client.query_api().query(query, org=org)

    # Hiển thị dữ liệu
    st.subheader("Dữ liệu từ InfluxDB")
    for table in tables:
        for record in table.records:
            if selected_measurement in ["http", "https"]:
                url_tag = record.values.get("url")
                st.write("URL:", url_tag)
            if selected_measurement in ["ping", "telnet"]:
                address_tag = record.values.get("address")
                st.write("Address:", address_tag)
            if selected_measurement == "telnet":
                port_tag = record.values.get("port")
                st.write("Port:", port_tag)
            st.write("Timestamp:", record.get_time(), "Field:", record.get_field(), "Value:", record.get_value())

    # Đóng kết nối
    client.close()

def chart_page():
    st.title("📊 Chart")

    # Chọn measurement để truy xuất dữ liệu
    selected_measurement = st.selectbox("Chọn measurement:", ["ping", "telnet", "http", "https"], key="chart_measurement")

    # Kết nối tới InfluxDB
    client = InfluxDBClient(url=url, token=token)

    while True:
        # Truy vấn dữ liệu từ InfluxDB
        query = f'from(bucket: "{bucket}") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "{selected_measurement}")'
        tables = client.query_api().query(query, org=org)

        # Tạo biểu đồ cho từng địa chỉ IP hoặc measurement
        charts = {}

        def process_record(record):
            if selected_measurement in ["http", "https"]:
                address_tag = record.values.get("url")
                return ("URL", address_tag)
            elif selected_measurement == "ping":
                address_tag = record.values.get("address")
                return ("Address", address_tag)
            elif selected_measurement == "telnet":
                address_tag = record.values.get("address")
                port_tag = record.values.get("port")
                return ("AddressPort", (address_tag, port_tag))

        for table in tables:
            for record in table.records:
                key = process_record(record)
                if key not in charts:
                    charts[key] = {
                        "chart_data": [],
                        "color_data": []
                    }

                value = int(record.get_value())  # Chuyển đổi giá trị thành số nguyên
                charts[key]["chart_data"].append((record.get_time(), value))
                if value == 1:
                    charts[key]["color_data"].append('red')
                elif value == 2:
                    charts[key]["color_data"].append('limegreen')
                else:
                    charts[key]["color_data"].append('blue')

        # Hiển thị các biểu đồ
        for key, chart_data in charts.items():
            selected_measurement, address_tag = key

            st.subheader(f"Chart: {address_tag}")

            if chart_data["chart_data"]:
                chart_df = pd.DataFrame(chart_data["chart_data"], columns=["Timestamp", "Value"])
                chart_df.set_index("Timestamp", inplace=True)

                fig = go.Figure(data=[go.Bar(x=chart_df.index, y=chart_df["Value"], marker=dict(color=chart_data["color_data"]))])
                fig.update_layout(xaxis_title="Timestamp", yaxis_title="Value")

                # Hiển thị biểu đồ trong Streamlit
                st.plotly_chart(fig, use_container_width=True)

        # Delay để cập nhật sau một khoảng thời gian
        time.sleep(10)  # Cập nhật sau ... giây

        # Rerun lại trang Streamlit để cập nhật dữ liệu mới
        st.experimental_rerun()

    # Đóng kết nối
    client.close()

# Hàm xử lý sự kiện khi người dùng nhấp vào nút "Add"
def add_check_action(check_type, ip_address=None, port=None, url=None, interval=None):
    if check_type and (ip_address or url) and interval is not None:
        threading.Thread(target=perform_auto_check, args=(check_type, ip_address, port, url, interval)).start()
        st.write("Đã thêm công việc tự động!")

# Hàm xử lý sự kiện khi người dùng nhấp vào nút "Stop"
def stop_auto_check():
    global is_running, is_running_kafka 
    is_running = False  
    is_running_kafka = False  

def add_check_page():
    st.title("🔮 Add Check")

    check_type = st.selectbox("Chọn loại kiểm tra:", ("Ping", "Telnet", "HTTP", "HTTPS"))

    if check_type == "Ping":
        ip_address = st.text_input("Nhập địa chỉ IP:")
        interval = st.slider("Chọn khoảng thời gian (giây):", 5, 60, 5)
        if st.button("Add"):
            add_check_action(check_type, ip_address, interval=interval)
        if st.button("Stop"):
            stop_auto_check()

    elif check_type == "Telnet":
        ip_address = st.text_input("Nhập địa chỉ IP:")
        port = st.text_input("Nhập cổng telnet:")
        interval = st.slider("Chọn khoảng thời gian (giây):", 5, 60, 5)
        if st.button("Add"):
            add_check_action(check_type, ip_address, port, interval=interval)
        if st.button("Stop"):
            stop_auto_check()

    elif check_type == "HTTP":
        http_url = st.text_input("Nhập URL HTTP:")
        interval = st.slider("Chọn khoảng thời gian (giây):", 5, 60, 5)
        if st.button("Add"):
            add_check_action(check_type, url=http_url, interval=interval)
        if st.button("Stop"):
            stop_auto_check()

    elif check_type == "HTTPS":
        https_url = st.text_input("Nhập URL HTTPS:")
        interval = st.slider("Chọn khoảng thời gian (giây):", 5, 60, 5)
        if st.button("Add"):
            add_check_action(check_type, url=https_url, interval=interval)
        if st.button("Stop"):
            stop_auto_check()

def main():
    st.sidebar.title("Dashboard")
    page = st.sidebar.selectbox("Chọn trang:", ("🚀 Ping & Telnet", "📡 HTTP & HTTPS", "🔮 Add Check","🚝 Event Log", "📊 Chart"))
    st.sidebar.success("Select a above.")

    if page == "🚀 Ping & Telnet":
        ping_telnet_page()
    elif page == "📡 HTTP & HTTPS":
        http_https_page()
    elif page == "🔮 Add Check":
        add_check_page()
    elif page == "🚝 Event Log":
        event_log_page()
    elif page == "📊 Chart":
        chart_page()

if __name__ == "__main__":
    main()
