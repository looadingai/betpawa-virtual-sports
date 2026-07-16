# pesapal_client.py - Working version for production
import requests
import base64
import json
import time

class PesaPalClient:
    def __init__(self, consumer_key, consumer_secret, environment='production'):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.environment = environment
        
        # Production URLs
        self.token_url = "https://pay.pesapal.com/v3/api/Auth/RequestToken"
        self.submit_order_url = "https://pay.pesapal.com/v3/api/Transactions/SubmitOrderRequest"
    
    def get_token(self):
        """Get OAuth token from PesaPal"""
        auth = base64.b64encode(f"{self.consumer_key}:{self.consumer_secret}".encode()).decode()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}"
        }
        
        try:
            response = requests.post(self.token_url, headers=headers, json={}, timeout=30)
            print(f"Token response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                token = result.get('token')
                if token:
                    return token
                else:
                    print(f"No token in response: {result}")
                    return None
            else:
                print(f"Token error {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Token exception: {str(e)}")
            return None
    
    def submit_order(self, amount, phone_number, email, order_reference, callback_url, ipn_id):
        """Submit order to trigger STK Push"""
        token = self.get_token()
        if not token:
            return {'success': False, 'error': 'Failed to get authentication token. Check your Consumer Key and Secret.'}
        
        # Clean phone number to 254 format
        phone = str(phone_number).strip()
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        elif phone.startswith('+'):
            phone = phone[1:]
        phone = ''.join(filter(str.isdigit, phone))
        
        # Prepare order data
        order_data = {
            "id": order_reference,
            "currency": "KES",
            "amount": str(round(float(amount), 2)),
            "description": f"BetPawa deposit {order_reference}",
            "callback_url": callback_url,
            "notification_id": ipn_id,
            "billing_address": {
                "email_address": email or f"user_{order_reference}@betpawa.com",
                "phone_number": phone,
                "country_code": "KE",
                "first_name": "BetPawa",
                "last_name": "User"
            }
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        try:
            print(f"Submitting order to: {self.submit_order_url}")
            response = requests.post(self.submit_order_url, json=order_data, headers=headers, timeout=60)
            print(f"Submit response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'redirect_url': result.get('redirect_url'),
                    'order_tracking_id': result.get('order_tracking_id'),
                    'merchant_reference': result.get('merchant_reference')
                }
            else:
                print(f"Submit error: {response.text}")
                return {'success': False, 'error': f'PesaPal error: {response.text}'}
        except Exception as e:
            print(f"Submit exception: {str(e)}")
            return {'success': False, 'error': f'Connection error: {str(e)}'}
