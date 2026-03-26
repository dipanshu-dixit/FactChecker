#!/usr/bin/env python3
"""Test script for API key and badge features."""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

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
    
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
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


def main():
    print("=" * 60)
    print("CrawlConda API Features Test Suite")
    print("=" * 60)
    
    # Test 1: Generate API key
    api_key = test_api_key_generation()
    if not api_key:
        print("\n❌ Cannot continue without API key")
        return
    
    # Test 2: Verify with API key
    ipfs_hash = test_verify_with_key(api_key)
    if not ipfs_hash:
        print("\n⚠️ Using existing hash for remaining tests")
        # Use a known hash for testing
        ipfs_hash = "QmSZ4qT8CmtWj3T5krB6WFKfiA6zbtPUQqvwVQAtn19wNx"
    
    # Test 3: Check usage
    test_api_key_usage(api_key)
    
    # Test 4: Badge SVG
    test_badge_svg(ipfs_hash)
    
    # Test 5: Badge embed
    test_badge_embed(ipfs_hash)
    
    # Test 6: Claim page
    test_claim_page(ipfs_hash)
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)
    print(f"\nYour API Key: {api_key}")
    print(f"Badge URL: {BASE_URL}/badge/{ipfs_hash}.svg")
    print(f"Claim Page: {BASE_URL}/claim/{ipfs_hash}")
    print(f"\nAPI Docs: http://localhost:3000/api-docs.html")


if __name__ == "__main__":
    main()
