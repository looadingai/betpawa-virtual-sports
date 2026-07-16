# pesapal_direct.py - Simple direct STK Push
import requests
import json
import time
import hashlib
import base64

class PesaPalDirect:
    def __init__(self, consumer_key, consumer_secret):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        
    def stk_push(self, amount, phone, order_id, callback_url):
        """Direct STK Push using simple API"""
        # Clean phone
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        
        # Simple request to PesaPal
        url = "https://pay.pesapal.com/api/PostPesapalDirectOrderV4"
        
        data = {
            'oauth_consumer_key': self.consumer_key,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_nonce': base64.b64encode(str(time.time()).encode()).decode(),
            'pesapal_merchant_reference': order_id,
            'pesapal_amount': str(amount),
            'pesapal_currency': 'KES',
            'pesapal_phone_number': phone,
            'pesapal_callback_url': callback_url,
            'pesapal_description': 'BetPawa Deposit',
        }
        
        # Make request
        response = requests.post(url, data=data)
        
        if response.status_code == 200:
            return {
                'success': True,
                'redirect_url': response.text.strip()
            }
        else:
            return {'success': False, 'error': response.text}
