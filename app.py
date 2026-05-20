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

# Account usage tracking
account_usage = {}  # {account_uid: {"daily_limit": 100, "used_today": 0, "last_reset": date}}
DAILY_LIMIT_PER_ACCOUNT = 100  # Default limit per account per day

def reset_daily_usage():
    """Reset daily usage counters at midnight"""
    today = datetime.datetime.now().date()
    for acc in account_usage:
        if account_usage[acc].get("last_reset") != today:
            account_usage[acc]["used_today"] = 0
            account_usage[acc]["last_reset"] = today

def can_account_send_like(account_uid):
    """Check if account can send more likes today"""
    today = datetime.datetime.now().date()
    if account_uid not in account_usage:
        account_usage[account_uid] = {
            "used_today": 0,
            "daily_limit": DAILY_LIMIT_PER_ACCOUNT,
            "last_reset": today
        }
    
    if account_usage[account_uid]["last_reset"] != today:
        account_usage[account_uid]["used_today"] = 0
        account_usage[account_uid]["last_reset"] = today
    
    return account_usage[account_uid]["used_today"] < account_usage[account_uid]["daily_limit"]

def increment_account_usage(account_uid):
    """Increment usage counter for account"""
    if account_uid in account_usage:
        account_usage[account_uid]["used_today"] += 1

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
        result = bytearray()
        uid = int(user_id)
        while uid > 0:
            byte = uid & 0x7F
            uid >>= 7
            if uid > 0:
                byte |= 0x80
            result.append(byte)
        
        final = bytearray()
        final.append(0x08)
        final.extend(result)
        
        region_bytes = region.encode('utf-8')
        final.append(0x12)
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
        uid_val = int(uid)
        while uid_val > 0:
            byte = uid_val & 0x7F
            uid_val >>= 7
            if uid_val > 0:
                byte |= 0x80
            result.append(byte)
        
        final = bytearray()
        final.append(0x08)
        final.extend(result)
        final.append(0x10)
        final.append(0x01)
        
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
        
        if response.status_code != 200:
            return None
        
        data = response.content
        likes = 0
        nickname = ""
        
        for i in range(len(data) - 4):
            if data[i] == 0x10:
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
        
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/LikeProfile"
        elif server_name in ["BR", "US"]:
            url = "https://client.us.freefiremobile.com/LikeProfile"
        else:
            url = "https://clientbp.ggpolarbear.com/LikeProfile"
        
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
        response = requests.post(url, data=edata, headers=headers, timeout=10, verify=False)
        
        if response.status_code == 200:
            return True, "Success"
        elif response.status_code == 401:
            return False, "Token expired/invalid"
        elif response.status_code == 403:
            return False, "Rate limited or banned"
        elif response.status_code == 500:
            return False, "Daily limit reached for this account"
        else:
            return False, f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "Request timeout"
    except Exception as e:
        return False, str(e)

# ========= NEW: LIKE WITH ACCOUNT LIMIT ==========
@app.route('/like-limit', methods=['GET'])
def like_with_limit():
    """
    Send likes with account limit
    Usage: /like-limit?uid=TARGET_UID&server=IND&accounts=5
    accounts: 1 to 999 (number of accounts to use)
    """
    target_uid = request.args.get('uid')
    server = request.args.get('server', '').upper()
    accounts_to_use = int(request.args.get('accounts', 999))  # Default 999 means all accounts
    
    if not target_uid:
        return jsonify({"error": "Target UID required"}), 400
    
    accounts = load_accounts()
    if not accounts:
        return jsonify({"error": "No accounts found in uidpass.json"}), 400
    
    # Reset daily usage
    reset_daily_usage()
    
    results = []
    success_count = 0
    account_limit_reached = 0
    accounts_used = 0
    
    print(f"\n🎯 Target: {target_uid}")
    print(f"📊 Accounts to use: {accounts_to_use} (Total available: {len(accounts)})")
    print(f"🌍 Server: {server or 'Auto'}")
    print("=" * 50)
    
    for i, acc in enumerate(accounts):
        # Stop if we've used the requested number of accounts
        if accounts_used >= accounts_to_use:
            print(f"\n✅ Reached requested limit of {accounts_to_use} accounts")
            break
        
        acc_uid = acc['uid']
        acc_password = acc['password']
        
        # Check if account has reached daily limit
        if not can_account_send_like(acc_uid):
            account_limit_reached += 1
            results.append({
                "account": acc_uid,
                "status": "limit_reached",
                "message": f"Daily limit ({DAILY_LIMIT_PER_ACCOUNT}) reached"
            })
            continue
        
        print(f"\n🔐 Using account: {acc_uid}")
        
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
            accounts_used += 1
            increment_account_usage(acc_uid)
            
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "region": use_server,
                "status": "success",
                "likes_sent": 1,
                "account_remaining": DAILY_LIMIT_PER_ACCOUNT - account_usage[acc_uid]["used_today"]
            })
            print(f"   ✅ Like sent from {acc_uid} (Remaining today: {DAILY_LIMIT_PER_ACCOUNT - account_usage[acc_uid]['used_today']})")
        else:
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "status": "failed",
                "error": msg
            })
            print(f"   ❌ Failed: {msg}")
        
        time.sleep(0.3)  # Delay between accounts
    
    return jsonify({
        "target_uid": int(target_uid),
        "server_used": server or "Auto",
        "accounts_requested": accounts_to_use,
        "accounts_used": accounts_used,
        "successful_likes": success_count,
        "total_accounts": len(accounts),
        "accounts_limit_reached": account_limit_reached,
        "daily_limit_per_account": DAILY_LIMIT_PER_ACCOUNT,
        "results": results,
        "account_usage": account_usage
    })

# ========= UPDATED: like-simple with account limit parameter ==========
@app.route('/like-simple', methods=['GET'])
def like_simple():
    """
    Send ONE like from each account (with optional account limit)
    Usage: /like-simple?uid=TARGET_UID&server=IND&accounts=5
    """
    target_uid = request.args.get('uid')
    server = request.args.get('server', '').upper()
    accounts_to_use = int(request.args.get('accounts', 999))  # Default all accounts
    
    if not target_uid:
        return jsonify({"error": "Target UID required"}), 400
    
    accounts = load_accounts()
    if not accounts:
        return jsonify({"error": "No accounts found"}), 400
    
    # Reset daily usage
    reset_daily_usage()
    
    results = []
    success_count = 0
    accounts_used = 0
    limit_reached_count = 0
    
    print(f"\n🔵 like-simple called with accounts={accounts_to_use}")
    
    for i, acc in enumerate(accounts):
        # Stop if we've used requested number of accounts
        if accounts_used >= accounts_to_use:
            print(f"✅ Reached limit of {accounts_to_use} accounts")
            break
        
        acc_uid = acc['uid']
        acc_password = acc['password']
        
        # Check daily limit
        if not can_account_send_like(acc_uid):
            limit_reached_count += 1
            results.append({
                "account": acc_uid,
                "status": "limit_reached",
                "message": f"Daily limit ({DAILY_LIMIT_PER_ACCOUNT}) reached"
            })
            continue
        
        print(f"\n🔐 Testing account: {acc_uid}")
        
        token, region, nickname, error = generate_jwt_from_guest(acc_uid, acc_password)
        
        if error or not token:
            results.append({
                "account": acc_uid,
                "status": "failed",
                "error": error or "Token generation failed"
            })
            continue
        
        use_server = server or region or "IND"
        success, msg = send_like_correct(target_uid, use_server, token, acc_uid)
        
        if success:
            success_count += 1
            accounts_used += 1
            increment_account_usage(acc_uid)
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "region": use_server,
                "status": "success",
                "likes_sent": 1,
                "remaining_today": DAILY_LIMIT_PER_ACCOUNT - account_usage[acc_uid]["used_today"]
            })
            print(f"   ✅ Success from {acc_uid}")
        else:
            results.append({
                "account": acc_uid,
                "nickname": nickname,
                "status": "failed",
                "error": msg
            })
            print(f"   ❌ Failed: {msg}")
        
        time.sleep(0.5)
    
    return jsonify({
        "target_uid": int(target_uid),
        "accounts_requested": accounts_to_use,
        "accounts_used": accounts_used,
        "successful_likes": success_count,
        "total_accounts": len(accounts),
        "accounts_limit_reached": limit_reached_count,
        "daily_limit_per_account": DAILY_LIMIT_PER_ACCOUNT,
        "results": results
    })

# ========= NEW: Get account usage stats ==========
@app.route('/usage', methods=['GET'])
def get_usage():
    """Get current account usage statistics"""
    reset_daily_usage()
    accounts = load_accounts()
    
    usage_stats = []
    for acc in accounts:
        acc_uid = acc['uid']
        if acc_uid in account_usage:
            usage_stats.append({
                "account": acc_uid,
                "used_today": account_usage[acc_uid]["used_today"],
                "daily_limit": account_usage[acc_uid]["daily_limit"],
                "remaining": account_usage[acc_uid]["daily_limit"] - account_usage[acc_uid]["used_today"]
            })
        else:
            usage_stats.append({
                "account": acc_uid,
                "used_today": 0,
                "daily_limit": DAILY_LIMIT_PER_ACCOUNT,
                "remaining": DAILY_LIMIT_PER_ACCOUNT
            })
    
    return jsonify({
        "total_accounts": len(accounts),
        "daily_limit_per_account": DAILY_LIMIT_PER_ACCOUNT,
        "accounts": usage_stats
    })

# ========= NEW: Reset account usage ==========
@app.route('/reset-usage', methods=['GET'])
def reset_usage():
    """Reset all account usage counters (admin only)"""
    global account_usage
    account_usage = {}
    return jsonify({"status": "success", "message": "All account usage counters reset"})

# ========= ORIGINAL ENDPOINTS (for backward compatibility) ==========
@app.route('/')
def index():
    accounts = load_accounts()
    return jsonify({
        "credit": "https://t.me/paglu_dev",
        "message": "FreeFire Like API - With Account Limit",
        "total_accounts": len(accounts),
        "daily_limit_per_account": DAILY_LIMIT_PER_ACCOUNT,
        "endpoints": {
            "/like-simple?uid=<target>&accounts=<1-999>": "Send 1 like from X accounts",
            "/like-limit?uid=<target>&accounts=<1-999>": "Send 1 like from X accounts (detailed)",
            "/like?uid=<target>&max=<n>": "Send multiple likes from all accounts",
            "/check?uid=<target>": "Check player likes",
            "/test-single?uid=<target>&account=<acc_uid>": "Test single account",
            "/add-account?uid=<uid>&password=<pwd>": "Add new account",
            "/usage": "View account usage statistics",
            "/reset-usage": "Reset usage counters (admin)"
        },
        "examples": {
            "Send from 1 account": "/like-simple?uid=1241124732&accounts=1",
            "Send from 5 accounts": "/like-simple?uid=1241124732&accounts=5",
            "Send from all accounts": "/like-simple?uid=1241124732",
            "Check usage": "/usage"
        }
    })

@app.route('/check', methods=['GET'])
def check_player():
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
    
    token, region, nickname, error = generate_jwt_from_guest(account_uid, account['password'])
    
    if error or not token:
        return jsonify({"error": f"Token failed: {error}"}), 500
    
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

@app.route('/like', methods=['GET'])
def like_multiple():
    target_uid = request.args.get('uid')
    server = request.args.get('server', '').upper()
    max_likes = int(request.args.get('max', 3))
    
    if not target_uid:
        return jsonify({"error": "Target UID required"}), 400
    
    accounts = load_accounts()
    results = []
    total_likes = 0
    
    reset_daily_usage()
    
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
            if not can_account_send_like(acc['uid']):
                print(f"   ⚠️ {acc['uid']} daily limit reached")
                break
                
            success, msg = send_like_correct(target_uid, use_server, token, acc['uid'])
            
            if success:
                account_likes += 1
                total_likes += 1
                increment_account_usage(acc['uid'])
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
    
    for acc in accounts:
        if acc['uid'] == uid:
            return jsonify({"error": "Account already exists"}), 400
    
    accounts.append({"uid": uid, "password": password})
    
    with open(UIDPASS_FILE, 'w') as f:
        json.dump(accounts, f, indent=2)
    
    token, region, nickname, error = generate_jwt_from_guest(uid, password)
    
    return jsonify({
        "status": "added",
        "uid": uid,
        "nickname": nickname if nickname else "Unknown",
        "region": region if region else "Unknown",
        "token_valid": token is not None
    })

if __name__ == '__main__':
    import datetime
    port = int(os.environ.get("PORT", 8080))
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║     🔥 FREE FIRE LIKE API - WITH ACCOUNT LIMIT 🔥        ║
    ╠══════════════════════════════════════════════════════════╣
    ║                                                           ║
    ║  NEW FEATURE: Account Limit Control                      ║
    ║                                                           ║
    ║  /like-simple?uid=1241124732&accounts=1   (1 account)   ║
    ║  /like-simple?uid=1241124732&accounts=5   (5 accounts)  ║
    ║  /like-simple?uid=1241124732              (all accounts)║
    ║                                                           ║
    ║  /usage - Check account usage                            ║
    ║  /reset-usage - Reset daily counters                     ║
    ║                                                           ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False)
