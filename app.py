from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import requests
import json
import base64
import jwt
import os
import struct
import time
import random

app = Flask(__name__)

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

UIDPASS_FILE = "uidpass.json"
JWT_API_URL = "http://87.232.72.68:3005/token"

def encrypt_message(plaintext):
    """Encrypt message with AES-CBC"""
    try:
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        padded = pad(plaintext, AES.block_size)
        encrypted = cipher.encrypt(padded)
        return binascii.hexlify(encrypted).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return None

def create_like_protobuf(user_id, region):
    """Create LikeProfile protobuf message - CORRECT FORMAT"""
    try:
        # Field 1: uid (int64) - tag 8
        result = bytearray()
        
        # Encode UID as varint
        uid = int(user_id)
        while uid > 0:
            byte = uid & 0x7F
            uid >>= 7
            if uid > 0:
                byte |= 0x80
            result.append(byte)
        
        # Tag for field 1 (uid) = 8
        final = bytearray()
        final.append(0x08)  # tag 1, type 0 (varint)
        final.extend(result)
        
        # Field 2: region (string) - tag 18
        region_bytes = region.encode('utf-8')
        final.append(0x12)  # tag 2, type 2 (string)
        final.append(len(region_bytes))
        final.extend(region_bytes)
        
        return bytes(final)
    except Exception as e:
        print(f"Like protobuf error: {e}")
        return None

def create_uid_protobuf(uid):
    """Create UID request protobuf"""
    try:
        result = bytearray()
        
        # Encode UID as varint
        uid_val = int(uid)
        while uid_val > 0:
            byte = uid_val & 0x7F
            uid_val >>= 7
            if uid_val > 0:
                byte |= 0x80
            result.append(byte)
        
        final = bytearray()
        final.append(0x08)  # tag 1, type 0
        final.extend(result)
        final.append(0x10)  # tag 2, type 0  
        final.append(0x01)  # value 1
        
        return bytes(final)
    except Exception as e:
        print(f"UID protobuf error: {e}")
        return None

def load_accounts():
    try:
        if os.path.exists(UIDPASS_FILE):
            with open(UIDPASS_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []

def generate_jwt_from_guest(uid, password):
    """Generate JWT from external API"""
    try:
        url = f"{JWT_API_URL}?uid={uid}&password={password}&key=dgop"
        response = requests.get(url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if 'token' in data:
                return data['token'], data.get('region', 'IND'), data.get('nickname', 'Unknown'), None
            else:
                return None, None, None, "No token in response"
        else:
            return None, None, None, f"API Error: {response.status_code}"
    except Exception as e:
        return None, None, None, str(e)

def get_player_info(uid, server_name, token):
    """Get player likes - with corrected request"""
    try:
        protobuf = create_uid_protobuf(uid)
        if not protobuf:
            return None
        
        encrypted = encrypt_message(protobuf)
        if not encrypted:
            return None
        
        # Correct URL based on region
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in ["BR", "US"]:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
        
        headers = {
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Unity-Version': '2018.4.11f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB53'
        }
        
        response = requests.post(url, data=bytes.fromhex(encrypted), headers=headers, timeout=10)
        
        print(f"GetInfo Response: {response.status_code}")
        
        if response.status_code != 200:
            return None
        
        # Parse response
        data = response.content
        likes = 0
        nickname = ""
        
        # Simple parsing for likes
        for i in range(len(data) - 4):
            if data[i] == 0x10:  # Field 2 (likes)
                j = i + 1
                value = 0
                shift = 0
                while j < len(data) and j < i + 10:
                    byte = data[j]
                    value |= (byte & 0x7F) << shift
                    j += 1
                    shift += 7
                    if not (byte & 0x80):
                        break
                likes = value
                break
        
        return {"likes": likes, "nickname": nickname}
    except Exception as e:
        print(f"Get info error: {e}")
        return None

def send_like_correct(uid, server_name, token, account_uid):
    """Send like with CORRECT format and headers"""
    try:
        protobuf = create_like_protobuf(uid, server_name)
        if not protobuf:
            return False, "Protobuf creation failed"
        
        encrypted = encrypt_message(protobuf)
        if not encrypted:
            return False, "Encryption failed"
        
        # Correct URL based on region
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/LikeProfile"
        elif server_name in ["BR", "US"]:
            url = "https://client.us.freefiremobile.com/LikeProfile"
        else:
            url = "https://clientbp.ggpolarbear.com/LikeProfile"
        
        # Complete headers exactly like original game
        headers = {
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Expect': '100-continue',
            'X-Unity-Version': '2018.4.11f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB53'
        }
        
        edata = bytes.fromhex(encrypted)
        
        print(f"   Sending like to: {url}")
        print(f"   Data length: {len(edata)} bytes")
        
        response = requests.post(url, data=edata, headers=headers, timeout=10, verify=False)
        
        print(f"   Response Status: {response.status_code}")
        
        if response.status_code == 200:
            # Check response content
            if len(response.content) > 0:
                print(f"   Response hex: {response.content.hex()[:50]}")
            return True, "Success"
        elif response.status_code == 401:
            return False, "Token expired/invalid"
        elif response.status_code == 403:
            return False, "Rate limited or banned"
        elif response.status_code == 500:
            # Sometimes 500 means like already given or daily limit reached
            return False, "Server error - possibly daily limit reached"
        else:
            return False, f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "Request timeout"
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    accounts = load_accounts()
    return jsonify({
        "credit": "https://t.me/paglu_dev",
        "message": "FreeFire Like API - Fixed Version",
        "total_accounts": len(accounts),
        "endpoints": {
            "/test-single?uid=<target>&account=<acc_uid>": "Test single account",
            "/like?uid=<target>": "Send likes from all accounts",
            "/like-simple?uid=<target>": "Simple like (1 per account)",
            "/check?uid=<target>": "Check player likes"
        }
    })

@app.route('/check', methods=['GET'])
def check_player():
    """Check player current likes"""
    target_uid = request.args.get('uid')
    server = request.args.get('server', 'IND').upper()
    
    if not target_uid:
        return jsonify({"error": "UID required"}), 400
    
    accounts = load_accounts()
    for acc in accounts:
        token, region, nickname, error = generate_jwt_from_guest(acc['uid'], acc['password'])
        if token:
            info = get_player_info(target_uid, server, token)
            if info:
                return jsonify({
                    "uid": int(target_uid),
                    "name": info.get('nickname', 'Unknown'),
                    "likes": info.get('likes', 0),
                    "server": server
                })
    
    return jsonify({"error": "Could not fetch player info"}), 500

@app.route('/test-single', methods=['GET'])
def test_single():
    """Test a single account"""
    target_uid = request.args.get('uid')
    account_uid = request.args.get('account')
    
    if not target_uid or not account_uid:
        return jsonify({"error": "Need uid (target) and account (account_uid)"}), 400
    
    accounts = load_accounts()
    account = None
    for acc in accounts:
        if acc['uid'] == account_uid:
            account = acc
            break
    
    if not account:
        return jsonify({"error": f"Account {account_uid} not found"}), 404
    
    # Generate token
    token, region, nickname, error = generate_jwt_from_guest(account_uid, account['password'])
    
    if error or not token:
        return jsonify({"error": f"Token failed: {error}"}), 500
    
    # Try to send like
    success, msg = send_like_correct(target_uid, region or "IND", token, account_uid)
    
    return jsonify({
        "account": account_uid,
        "nickname": nickname,
        "region": region,
        "target": int(target_uid),
        "like_sent": success,
        "message": msg,
        "token_valid": True
    })

@app.route('/like-simple', methods=['GET'])
def like_simple():
    """Send ONE like from each account (simple and fast)"""
    target_uid = request.args.get('uid')
    server = request.args.get('server', '').upper()
    
    if not target_uid:
        return jsonify({"error": "Target UID required"}), 400
    
    accounts = load_accounts()
    if not accounts:
        return jsonify({"error": "No accounts found"}), 400
    
    results = []
    success_count = 0
    
    for acc in accounts:
        acc_uid = acc['uid']
        acc_password = acc['password']
        
        print(f"\n🔐 Testing account: {acc_uid}")
        
        # Generate token
        token, region, nickname, error = generate_jwt_from_guest(acc_uid, acc_password)
        
        if error or not token:
            results.append({
                "account": acc_uid,
                "status": "failed",
                "error": error or "Token generation failed"
            })
            continue
        
        # Use specified server or account's region
        use_server = server or region or "IND"
        
        # Send like
        success, msg = send_like_correct(target_uid, use_server, token, acc_uid)
        
        if success:
            success_count += 1
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "region": use_server,
                "status": "success",
                "message": msg
            })
        else:
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "status": "failed",
                "error": msg
            })
        
        time.sleep(0.5)  # Delay between accounts
    
    return jsonify({
        "target_uid": int(target_uid),
        "successful_likes": success_count,
        "total_accounts": len(accounts),
        "results": results
    })

@app.route('/like', methods=['GET'])
def like_multiple():
    """Send multiple likes from each account"""
    target_uid = request.args.get('uid')
    server = request.args.get('server', '').upper()
    max_likes = int(request.args.get('max', 3))
    
    if not target_uid:
        return jsonify({"error": "Target UID required"}), 400
    
    accounts = load_accounts()
    results = []
    total_likes = 0
    
    for acc in accounts:
        token, region, nickname, error = generate_jwt_from_guest(acc['uid'], acc['password'])
        
        if error or not token:
            results.append({
                "account": acc['uid'],
                "status": "failed",
                "error": error
            })
            continue
        
        use_server = server or region or "IND"
        account_likes = 0
        
        for i in range(max_likes):
            success, msg = send_like_correct(target_uid, use_server, token, acc['uid'])
            
            if success:
                account_likes += 1
                total_likes += 1
                print(f"   ✅ {acc['uid']} like {i+1} success")
            else:
                print(f"   ❌ {acc['uid']} like {i+1} failed: {msg}")
                if "401" in msg or "expired" in msg:
                    break
            
            time.sleep(0.3)
        
        results.append({
            "account": acc['uid'],
            "nickname": nickname,
            "region": use_server,
            "likes_sent": account_likes,
            "status": "success" if account_likes > 0 else "failed"
        })
    
    return jsonify({
        "target_uid": int(target_uid),
        "total_likes_sent": total_likes,
        "accounts_used": len([r for r in results if r['status'] == 'success']),
        "total_accounts": len(accounts),
        "details": results
    })

@app.route('/add-account', methods=['GET'])
def add_account():
    uid = request.args.get('uid')
    password = request.args.get('password')
    
    if not uid or not password:
        return jsonify({"error": "uid and password required"}), 400
    
    accounts = load_accounts()
    
    # Check if exists
    for acc in accounts:
        if acc['uid'] == uid:
            return jsonify({"error": "Account already exists"}), 400
    
    accounts.append({"uid": uid, "password": password})
    
    with open(UIDPASS_FILE, 'w') as f:
        json.dump(accounts, f, indent=2)
    
    # Test the account
    token, region, nickname, error = generate_jwt_from_guest(uid, password)
    
    return jsonify({
        "status": "added",
        "uid": uid,
        "nickname": nickname if nickname else "Unknown",
        "region": region if region else "Unknown",
        "token_valid": token is not None
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     🔥 FREE FIRE LIKE API - FIXED VERSION 🔥             ║
    ╠══════════════════════════════════════════════════════════╣
    ║                                                           ║
    ║  USE THESE ENDPOINTS:                                    ║
    ║                                                           ║
    ║  1. Check player likes:                                  ║
    ║     /check?uid=1241124732                                ║
    ║                                                           ║
    ║  2. Send 1 like from each account (RECOMMENDED):        ║
    ║     /like-simple?uid=1241124732                          ║
    ║                                                           ║
    ║  3. Test single account:                                 ║
    ║     /test-single?uid=1241124732&account=4549583213      ║
    ║                                                           ║
    ║  4. Add new account:                                     ║
    ║     /add-account?uid=123456&password=HASH               ║
    ║                                                           ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False)