#!/usr/bin/env python3
"""Integration tests for API key and badge features."""

import requests
import time
import pytest

BASE_URL = "http://localhost:8000"

@pytest.fixture(scope="session")
def server_available():
    """Skip integration tests when local API server is not running."""
    try:
        requests.get(f"{BASE_URL}/health", timeout=3)
    except requests.RequestException:
        pytest.skip("Local API server is not running on http://localhost:8000")


@pytest.fixture(scope="session")
def api_key(server_available):
    """Generate an API key once for the full test session."""
    response = requests.post(
        f"{BASE_URL}/api-keys/generate",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "use_case": "Testing API features"
        },
        timeout=30
    )
    assert response.status_code == 200, response.text
    return response.json()["api_key"]


@pytest.fixture(scope="session")
def ipfs_hash(api_key):
    """Create one verification result and reuse its hash for dependent tests."""
    response = requests.get(
        f"{BASE_URL}/verify",
        params={"claim": "Test claim for API"},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120,
    )
    assert response.status_code == 200, response.text
    return response.json()["ipfs_hash"]


def test_rate_limit_without_key(server_available):
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


def test_api_key_generation(server_available):
    """Test API key generation endpoint without relying on fixture state."""
    response = requests.post(
        f"{BASE_URL}/api-keys/generate",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "use_case": "Testing API features"
        },
        timeout=30,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "api_key" in data
    assert data.get("daily_limit", 0) > 0


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
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert "verdict" in data
    assert "ipfs_hash" in data


def test_api_key_usage(api_key):
    """Test API key usage endpoint."""
    print("\n📊 Testing API Key Usage...")
    
    response = requests.get(
        f"{BASE_URL}/api-keys/usage",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert "requests_today" in data
    assert "daily_limit" in data


def test_badge_svg(ipfs_hash):
    """Test badge SVG generation."""
    print("\n🎨 Testing Badge SVG...")
    
    response = requests.get(f"{BASE_URL}/badge/{ipfs_hash}.svg")
    
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert len(response.content) > 0


def test_badge_embed(ipfs_hash):
    """Test badge embed codes."""
    print("\n📝 Testing Badge Embed Codes...")
    
    response = requests.get(f"{BASE_URL}/badge/{ipfs_hash}/embed")
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert "embed" in data
    assert "html" in data["embed"]
    assert "markdown" in data["embed"]


def test_claim_page(ipfs_hash):
    """Test claim page with OG tags."""
    print("\n🔗 Testing Claim Page...")
    
    response = requests.get(f"{BASE_URL}/claim/{ipfs_hash}")
    
    assert response.status_code == 200
    html = response.text
    assert 'og:title' in html and 'og:image' in html
    assert 'twitter:card' in html


def test_rate_limit_with_key(api_key):
    """Test API key rate limit (100 requests/day)."""
    print("\n🔐 Testing Rate Limit WITH API Key...")
    print("   Limit: 100 requests per day (free tier)")
    
    for i in range(3):
        response = requests.get(
            f"{BASE_URL}/verify",
            params={"claim": f"Test with key {i+1}"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120
        )
        assert response.status_code in (200, 429), response.text
        if response.status_code == 429:
            break
        time.sleep(2)

    usage_res = requests.get(
        f"{BASE_URL}/api-keys/usage",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    assert usage_res.status_code == 200, usage_res.text
    data = usage_res.json()
    assert data["requests_today"] <= data["daily_limit"]


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
