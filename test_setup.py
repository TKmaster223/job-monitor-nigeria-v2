#!/usr/bin/env python3
"""
Test script to verify job monitor setup
Run this before deploying to GitHub Actions
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_imports():
    """Test all required imports"""
    print("Testing imports...")
    try:
        import requests
        import bs4
        import yaml
        import schedule
        print("[OK] All imports successful")
        return True
    except ImportError as e:
        print(f"[FAIL] Import error: {e}")
        return False

def test_config():
    """Test config loading"""
    print("\nTesting config...")
    try:
        import yaml
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        print("[OK] Config loaded successfully")
        print(f"  - Job sites enabled: {[k for k,v in config['job_sites'].items() if v]}")
        print(f"  - Keywords: {len(config['job_search']['keywords'])}")
        print(f"  - Check interval: {config['monitoring']['check_interval_minutes']} minutes")
        return True
    except Exception as e:
        print(f"[FAIL] Config error: {e}")
        return False

def test_env_vars():
    """Test environment variables"""
    print("\nTesting environment variables...")
    sender = os.getenv('SENDER_EMAIL')
    password = os.getenv('SENDER_PASSWORD')
    recipient = os.getenv('RECIPIENT_EMAIL')
    
    if sender and password and recipient:
        print("[OK] All environment variables set")
        print(f"  - Sender: {sender}")
        print(f"  - Recipient: {recipient}")
        return True
    else:
        print("[WARN] Some environment variables missing:")
        if not sender: print("  - SENDER_EMAIL not set")
        if not password: print("  - SENDER_PASSWORD not set")
        if not recipient: print("  - RECIPIENT_EMAIL not set")
        print("  (This is OK for GitHub Actions - secrets will be used there)")
        return True  # Not a failure for GitHub Actions

def test_gmail_connection():
    """Test Gmail SMTP connection"""
    print("\nTesting Gmail SMTP connection...")
    sender = os.getenv('SENDER_EMAIL')
    password = os.getenv('SENDER_PASSWORD')
    
    if not sender or not password:
        print("[WARN] Skipping - credentials not in environment")
        return True
    
    import smtplib
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
        print("[OK] Gmail SMTP connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] Gmail SMTP error: {e}")
        print("  Make sure you're using an App Password, not your regular password")
        return False

def test_scrapers():
    """Test scraper initialization"""
    print("\nTesting scraper initialization...")
    try:
        import yaml
        from job_monitor import JobMonitor
        
        monitor = JobMonitor('config.yaml')
        print(f"[OK] JobMonitor initialized with {len(monitor.scrapers)} scrapers:")
        for name in monitor.scrapers:
            print(f"  - {name}")
        return True
    except Exception as e:
        print(f"[FAIL] Scraper initialization error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_email():
    """Send test email"""
    print("\nTesting email sending...")
    sender = os.getenv('SENDER_EMAIL')
    password = os.getenv('SENDER_PASSWORD')
    recipient = os.getenv('RECIPIENT_EMAIL')
    
    if not all([sender, password, recipient]):
        print("[WARN] Skipping - credentials not in environment")
        return True
    
    try:
        from job_monitor import EmailNotifier
        import yaml
        
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        notifier = EmailNotifier(config)
        
        from job_monitor import Job
        test_job = Job(
            title="Test Job - Software Developer Intern",
            company="Test Company Ltd",
            location="Abuja, Nigeria",
            url="https://example.com/test-job",
            source="Test"
        )
        
        result = notifier.send_jobs([test_job])
        if result:
            print("[OK] Test email sent successfully!")
            print(f"  Check {recipient} for the test email")
        else:
            print("[FAIL] Failed to send test email")
        return result
    except Exception as e:
        print(f"[FAIL] Email test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 50)
    print("Job Monitor Setup Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_config,
        test_env_vars,
        test_gmail_connection,
        test_scrapers,
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("\n" + "=" * 50)
    print("Summary")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"[OK] All {total} tests passed!")
        print("\nReady to deploy to GitHub Actions!")
        print("\nNext steps:")
        print("1. Push to GitHub")
        print("2. Add secrets in GitHub repository settings")
        print("3. Enable Actions workflow")
        return 0
    else:
        print(f"[FAIL] {total - passed} of {total} tests failed")
        print("\nFix the issues above before deploying")
        return 1

if __name__ == "__main__":
    sys.exit(main())