"""API Key management system for CrawlConda."""
import secrets
import hashlib
from datetime import datetime, timezone
from typing import Optional
import chromadb

# API key format: cc_live_<32_hex_chars>
# Stored as SHA256 hash in ChromaDB

class APIKeyManager:
    def __init__(self, chroma_client: chromadb.PersistentClient):
        self.keys_col = chroma_client.get_or_create_collection("api_keys")
    
    def generate_key(self, name: str, email: str, tier: str = "free") -> str:
        """Generate a new API key.
        
        Args:
            name: User/organization name
            email: Contact email
            tier: "free" (100/day) or "pro" (1000/day)
        
        Returns:
            Plain API key (only shown once)
        """
        # Generate random key
        random_part = secrets.token_hex(16)  # 32 hex chars
        api_key = f"cc_live_{random_part}"
        
        # Hash for storage
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Store metadata
        self.keys_col.add(
            ids=[key_hash],
            documents=[api_key[:10] + "..." + api_key[-4:]],  # Partial key for display
            metadatas=[{
                "name": name[:100],
                "email": email[:100],
                "tier": tier,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "requests_today": 0,
                "last_reset": datetime.now(tz=timezone.utc).date().isoformat(),
                "total_requests": 0,
                "active": True,
            }]
        )
        
        return api_key
    
    def validate_key(self, api_key: str) -> Optional[dict]:
        """Validate API key and return metadata.
        
        Returns:
            Metadata dict if valid, None if invalid
        """
        if not api_key or not api_key.startswith("cc_live_"):
            return None
        
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        try:
            result = self.keys_col.get(ids=[key_hash])
            if not result["ids"]:
                return None
            
            meta = result["metadatas"][0]
            
            # Check if active
            if not meta.get("active", True):
                return None
            
            return meta
        except Exception:
            return None
    
    def increment_usage(self, api_key: str) -> bool:
        """Increment request counter for API key.
        
        Returns:
            True if under limit, False if rate limited
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        try:
            result = self.keys_col.get(ids=[key_hash])
            if not result["ids"]:
                return False
            
            meta = result["metadatas"][0]
            
            # Reset daily counter if new day
            today = datetime.now(tz=timezone.utc).date().isoformat()
            if meta.get("last_reset") != today:
                meta["requests_today"] = 0
                meta["last_reset"] = today
            
            # Check rate limit
            tier = meta.get("tier", "free")
            limit = 1000 if tier == "pro" else 100
            
            if meta["requests_today"] >= limit:
                return False
            
            # Increment counters
            meta["requests_today"] += 1
            meta["total_requests"] = meta.get("total_requests", 0) + 1
            
            # Update in DB
            self.keys_col.update(
                ids=[key_hash],
                metadatas=[meta]
            )
            
            return True
        except Exception:
            return False
    
    def get_usage(self, api_key: str) -> Optional[dict]:
        """Get usage stats for API key."""
        meta = self.validate_key(api_key)
        if not meta:
            return None
        
        tier = meta.get("tier", "free")
        limit = 1000 if tier == "pro" else 100
        
        return {
            "tier": tier,
            "requests_today": meta.get("requests_today", 0),
            "daily_limit": limit,
            "total_requests": meta.get("total_requests", 0),
            "created_at": meta.get("created_at"),
        }
    
    def revoke_key(self, api_key: str) -> bool:
        """Revoke an API key."""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        try:
            result = self.keys_col.get(ids=[key_hash])
            if not result["ids"]:
                return False
            
            meta = result["metadatas"][0]
            meta["active"] = False
            
            self.keys_col.update(
                ids=[key_hash],
                metadatas=[meta]
            )
            
            return True
        except Exception:
            return False
