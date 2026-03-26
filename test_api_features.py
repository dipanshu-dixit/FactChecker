#!/usr/bin/env python3
"""Test script for API key and badge features."""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_rate_limit_without_key():
    """Test IP-based rate limit (5 requests/hour)."""
    print("\n🔒 Testing Rate Limit WITHOUT API Key...")
    print("   Limit: 5 requests per hour per IP")
    
    for i in range(6):
        try:
            response = requests.get(
                f"{BASE_URL}/verify",
                params={"claim": f"Test claim {i+1}"},
                timeout=120
            )
            
            if response.status_code == 200:
                print(f"   ✅ Request {i+1}/6: Success")
            elif response.status_code == 429:
                print(f"   ❌ Request {i+1}/6: Rate limited!")
                print(f"      Message: {response.json().get('detail')}")
                print(f"\n   💡 You hit the limit after {i} requests")
                print(f"      Get an API key for 100 requests/day!")
                break
            else:
                print(f"   ⚠️  Request {i+1}/6: HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ Request {i+1}/6: {e}")
        
        if i < 5:
            time.sleep(2)


def test_api_key_generation():
    """Test API key generation."""
    print("\n🔑 Testing API Key Generation...")
    
    response = requests.post(
        f"{BASE_URL}/api-keys/generate",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "use_case": "Testing API features"
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ API Key generated: {data['api_key'][:20]}...")
        print(f"   Tier: {data['tier']}, Limit: {data['daily_limit']}/day")
        return data['api_key']
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")
        return None


def test_verify_with_key(api_key):
    """Test verification with API key."""
    print("\n🔍 Testing Verification with API Key...")
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    response = requests.get(
        f"{BASE_URL}/verify",
        params={"claim": "Test claim for API"},
        headers=headers,
        timeout=120
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Verification successful")
        print(f"   Verdict: {data['verdict']}")
        print(f"   IPFS Hash: {data['ipfs_hash']}")
        return data['ipfs_hash']
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")
        return None


def test_api_key_usage(api_key):
    """Test API key usage endpoint."""
    print("\n📊 Testing API Key Usage...")
    
    response = requests.get(
        f"{BASE_URL}/api-keys/usage",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Usage retrieved")
        print(f"   Requests today: {data['requests_today']}/{data['daily_limit']}")
        print(f"   Total requests: {data['total_requests']}")
    else:
        print(f"❌ Failed: {response.status_code} - {response.text}")


def test_badge_svg(ipfs_hash):
    """Test badge SVG generation."""
    print("\n🎨 Testing Badge SVG...")
    
    response = requests.get(f"{BASE_URL}/badge/{ipfs_hash}.svg")
    
    if response.status_code == 200:
        print(f"✅ Badge SVG generated ({len(response.content)} bytes)")
        print(f"   Content-Type: {response.headers.get('content-type')}")
    else:
        print(f"❌ Failed: {response.status_code}")


def test_badge_embed(ipfs_hash):
    """Test badge embed codes."""
    print("\n📝 Testing Badge Embed Codes...")
    
    response = requests.get(f"{BASE_URL}/badge/{ipfs_hash}/embed")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Embed codes generated")
        print(f"   HTML: {data['embed']['html'][:60]}...")
        print(f"   Markdown: {data['embed']['markdown'][:60]}...")
    else:
        print(f"❌ Failed: {response.status_code}")


def test_claim_page(ipfs_hash):
    """Test claim page with OG tags."""
    print("\n🔗 Testing Claim Page...")
    
    response = requests.get(f"{BASE_URL}/claim/{ipfs_hash}")
    
    if response.status_code == 200:
        html = response.text
        has_og_tags = 'og:title' in html and 'og:image' in html
        has_twitter_tags = 'twitter:card' in html
        
        print(f"✅ Claim page generated ({len(html)} bytes)")
        print(f"   Open Graph tags: {'✓' if has_og_tags else '✗'}")
        print(f"   Twitter Card tags: {'✓' if has_twitter_tags else '✗'}")
    else:
        print(f"❌ Failed: {response.status_code}")


def test_rate_limit_with_key(api_key):
    """Test API key rate limit (100 requests/day)."""
    print("\n🔐 Testing Rate Limit WITH API Key...")
    print("   Limit: 100 requests per day (free tier)")
    
    try:
        for i in range(3):
            response = requests.get(
                f"{BASE_URL}/verify",
                params={"claim": f"Test with key {i+1}"},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120
            )
            
            if response.status_code == 200:
                print(f"   ✅ Request {i+1}/3: Success (using API key)")
            elif response.status_code == 429:
                print(f"   ❌ Request {i+1}/3: Rate limited (100/day exceeded)")
                break
            
            time.sleep(2)
        
        usage_res = requests.get(
            f"{BASE_URL}/api-keys/usage",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        
        if usage_res.ok:
            data = usage_res.json()
            print(f"\n   📊 Current usage: {data['requests_today']}/{data['daily_limit']}")
            remaining = data['daily_limit'] - data['requests_today']
            print(f"   🔥 Remaining today: {remaining} requests")
    except Exception as e:
        print(f"   ❌ Failed: {e}")


def main():
    print("=" * 60)
    print("CrawlConda API Features Test Suite")
    print("=" * 60)
    
    # Test 1: Rate limit without key
    test_rate_limit_without_key()
    
    print("\n" + "=" * 60)
    input("\nPress Enter to continue with API key tests...")
    print("=" * 60)
    
    # Test 2: Generate API key
    api_key = test_api_key_generation()
    if not api_key:
        print("\n❌ Cannot continue without API key")
        return
    
    # Test 3: Verify with API key
    ipfs_hash = test_verify_with_key(api_key)
    if not ipfs_hash:
        print("\n⚠️ Using existing hash for remaining tests")
        ipfs_hash = "QmSZ4qT8CmtWj3T5krB6WFKfiA6zbtPUQqvwVQAtn19wNx"
    
    # Test 4: Check usage
    test_api_key_usage(api_key)
    
    # Test 5: Badge SVG
    test_badge_svg(ipfs_hash)
    
    # Test 6: Badge embed
    test_badge_embed(ipfs_hash)
    
    # Test 7: Claim page
    test_claim_page(ipfs_hash)
    
    # Test 8: Rate limit with key
    test_rate_limit_with_key(api_key)
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)
    print(f"\n📋 Summary:")
    print(f"   API Key: {api_key}")
    print(f"   Badge URL: {BASE_URL}/badge/{ipfs_hash}.svg")
    print(f"   Claim Page: {BASE_URL}/claim/{ipfs_hash}")
    print(f"\n🌐 Web Pages:")
    print(f"   Settings: http://localhost:3000/settings.html")
    print(f"   API Docs: http://localhost:3000/api-docs.html")
    print(f"\n📊 Rate Limits:")
    print(f"   Without API key: 5 requests/hour per IP")
    print(f"   With API key (free): 100 requests/day")
    print(f"   With API key (pro): 1,000 requests/day")


if __name__ == "__main__":
    main()
