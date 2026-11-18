#!/usr/bin/env python3
"""
Job Monitor for Nigerian Job Sites
Monitors multiple job sites for developer/internship roles in Abuja, Nigeria
Sends email notifications via Gmail SMTP
"""

import os
import re
import json
import time
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Windows-compatible log symbols
LOG_OK = "[OK]"
LOG_FAIL = "[FAIL]"
LOG_WARN = "[WARN]"
LOG_INFO = "[INFO]"


@dataclass
class Job:
    """Represents a job posting"""
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_date: Optional[str] = None
    description: Optional[str] = None
    job_type: Optional[str] = None  # full-time, internship, contract, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def matches_keywords(self, keywords: List[str], exclude_keywords: List[str]) -> bool:
        """Check if job matches search criteria"""
        text = f"{self.title} {self.description or ''} {self.company}".lower()
        
        # Check exclude keywords first
        for exclude in exclude_keywords:
            if exclude.lower() in text:
                return False
        
        # Check include keywords
        for keyword in keywords:
            if keyword.lower() in text:
                return True
        
        return False


class JobSiteScraper:
    """Base class for job site scrapers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        })
    
    def scrape(self) -> List[Job]:
        """Scrape jobs from the site - to be implemented by subclasses"""
        raise NotImplementedError
    
    def _get_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a page"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None


class LinkedInScraper(JobSiteScraper):
    """Scrape LinkedIn Jobs"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        location = self.config['job_search']['location']
        
        # LinkedIn uses a specific URL structure for job search
        # We'll use the guest search API approach
        for keyword in keywords[:5]:  # Limit to first 5 keywords to avoid rate limiting
            try:
                url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                params = {
                    'keywords': keyword,
                    'location': location,
                    'start': 0,
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('li')
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping LinkedIn for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h3', class_=re.compile(r'base-search-card__title'))
            company_elem = card.find('h4', class_=re.compile(r'base-search-card__subtitle'))
            location_elem = card.find('span', class_=re.compile(r'job-search-card__location'))
            link_elem = card.find('a', class_=re.compile(r'base-card__full-link'))
            
            if not title_elem or not link_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Unknown"
            url = link_elem.get('href', '')
            
            # Make URL absolute
            if url and not url.startswith('http'):
                url = urljoin('https://www.linkedin.com', url)
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='LinkedIn'
            )
        except Exception as e:
            logger.error(f"Error parsing LinkedIn job card: {e}")
            return None


class IndeedScraper(JobSiteScraper):
    """Scrape Indeed Nigeria"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        location = "Abuja"  # Indeed uses city name
        
        for keyword in keywords[:5]:
            try:
                url = "https://ng.indeed.com/jobs"
                params = {
                    'q': keyword,
                    'l': location,
                    'sort': 'date',
                    'fromage': self.config['monitoring']['days_back'],
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('div', class_=re.compile(r'job_seen_beacon|result'))
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping Indeed for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h2', class_=re.compile(r'jobTitle'))
            company_elem = card.find('span', class_=re.compile(r'companyName'))
            location_elem = card.find('div', class_=re.compile(r'companyLocation'))
            link_elem = card.find('a', class_=re.compile(r'jcs-JobTitle'))
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Abuja"
            
            url = ""
            if link_elem and link_elem.get('href'):
                url = urljoin('https://ng.indeed.com', link_elem['href'])
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='Indeed Nigeria'
            )
        except Exception as e:
            logger.error(f"Error parsing Indeed job card: {e}")
            return None


class JobbermanScraper(JobSiteScraper):
    """Scrape Jobberman Nigeria"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        
        for keyword in keywords[:5]:
            try:
                url = "https://www.jobberman.com/jobs"
                params = {
                    'keyword': keyword,
                    'location': 'Abuja',
                    'sort': 'newest',
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('article', class_=re.compile(r'job-card'))
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping Jobberman for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h3', class_=re.compile(r'job-title'))
            company_elem = card.find('div', class_=re.compile(r'company-name'))
            location_elem = card.find('span', class_=re.compile(r'location'))
            link_elem = card.find('a', href=True)
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Abuja"
            
            url = ""
            if link_elem and link_elem.get('href'):
                url = urljoin('https://www.jobberman.com', link_elem['href'])
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='Jobberman'
            )
        except Exception as e:
            logger.error(f"Error parsing Jobberman job card: {e}")
            return None


class MyJobMagScraper(JobSiteScraper):
    """Scrape MyJobMag Nigeria"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        
        for keyword in keywords[:5]:
            try:
                url = "https://www.myjobmag.com/search/jobs"
                params = {
                    'q': keyword,
                    'location': 'abuja',
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('li', class_=re.compile(r'job-list'))
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping MyJobMag for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h2') or card.find('h3')
            company_elem = card.find('span', class_=re.compile(r'company'))
            location_elem = card.find('span', class_=re.compile(r'location'))
            link_elem = card.find('a', href=True)
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Abuja"
            
            url = ""
            if link_elem and link_elem.get('href'):
                url = urljoin('https://www.myjobmag.com', link_elem['href'])
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='MyJobMag'
            )
        except Exception as e:
            logger.error(f"Error parsing MyJobMag job card: {e}")
            return None


class NgCareersScraper(JobSiteScraper):
    """Scrape NgCareers"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        
        for keyword in keywords[:5]:
            try:
                url = "https://www.ngcareers.com/jobs"
                params = {
                    'keyword': keyword,
                    'location': 'Abuja',
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('div', class_=re.compile(r'job-item'))
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping NgCareers for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h3') or card.find('h2')
            company_elem = card.find('span', class_=re.compile(r'company'))
            location_elem = card.find('span', class_=re.compile(r'location'))
            link_elem = card.find('a', href=True)
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Abuja"
            
            url = ""
            if link_elem and link_elem.get('href'):
                url = urljoin('https://www.ngcareers.com', link_elem['href'])
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='NgCareers'
            )
        except Exception as e:
            logger.error(f"Error parsing NgCareers job card: {e}")
            return None


class HotNigerianJobsScraper(JobSiteScraper):
    """Scrape Hot Nigerian Jobs"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        
        for keyword in keywords[:5]:
            try:
                url = "https://www.hotnigerianjobs.com/search"
                params = {
                    'q': keyword,
                    'location': 'Abuja',
                }
                
                soup = self._get_page_with_params(url, params)
                if not soup:
                    continue
                
                job_cards = soup.find_all('div', class_=re.compile(r'job-post'))
                for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                    job = self._parse_job_card(card)
                    if job:
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping Hot Nigerian Jobs for '{keyword}': {e}")
        
        return jobs
    
    def _get_page_with_params(self, url: str, params: Dict) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def _parse_job_card(self, card) -> Optional[Job]:
        try:
            title_elem = card.find('h2') or card.find('h3')
            company_elem = card.find('span', class_=re.compile(r'company'))
            location_elem = card.find('span', class_=re.compile(r'location'))
            link_elem = card.find('a', href=True)
            
            if not title_elem:
                return None
            
            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            location = location_elem.get_text(strip=True) if location_elem else "Abuja"
            
            url = ""
            if link_elem and link_elem.get('href'):
                url = urljoin('https://www.hotnigerianjobs.com', link_elem['href'])
            
            return Job(
                title=title,
                company=company,
                location=location,
                url=url,
                source='Hot Nigerian Jobs'
            )
        except Exception as e:
            logger.error(f"Error parsing Hot Nigerian Jobs job card: {e}")
            return None


class EmailNotifier:
    """Send email notifications for new jobs"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config['email']
    
    def send_jobs(self, jobs: List[Job]) -> bool:
        """Send email with new job listings"""
        if not jobs:
            logger.info("No new jobs to notify about")
            return True
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[JOB ALERT] {len(jobs)} New Job Opportunities in Abuja - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            msg['From'] = self.config['sender_email']
            msg['To'] = self.config['recipient_email']
            
            # Create HTML content
            html = self._create_html_email(jobs)
            text = self._create_text_email(jobs)
            
            msg.attach(MIMEText(text, 'plain'))
            msg.attach(MIMEText(html, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                server.starttls()
                server.login(self.config['sender_email'], self.config['sender_password'])
                server.send_message(msg)
            
            logger.info(f"Email sent successfully with {len(jobs)} jobs")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def _create_html_email(self, jobs: List[Job]) -> str:
        """Create HTML email content"""
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ padding: 20px; background: #f9f9f9; }}
                .job {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .job-title {{ font-size: 18px; font-weight: bold; color: #667eea; margin-bottom: 5px; }}
                .job-company {{ color: #555; font-size: 16px; margin-bottom: 5px; }}
                .job-location {{ color: #888; font-size: 14px; margin-bottom: 10px; }}
                .job-source {{ display: inline-block; background: #e0e0e0; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 10px; }}
                .job-link {{ display: inline-block; background: #667eea; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; margin-top: 10px; }}
                .job-link:hover {{ background: #5568d3; }}
                .footer {{ text-align: center; padding: 20px; color: #888; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>[JOB ALERT] New Job Opportunities Found!</h1>
                <p>Found {len(jobs)} new developer/internship roles in Abuja, Nigeria</p>
            </div>
            <div class="content">
        """
        
        for job in jobs:
            html += f"""
                <div class="job">
                    <div class="job-title">{job.title}</div>
                    <div class="job-company">[COMPANY] {job.company}</div>
                    <div class="job-location">[LOCATION] {job.location}</div>
                    <span class="job-source">{job.source}</span>
                    <a href="{job.url}" class="job-link" target="_blank">View Job →</a>
                </div>
            """
        
        html += f"""
            </div>
            <div class="footer">
                <p>Job Monitor Bot | Running on GitHub Actions | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>To unsubscribe, disable the GitHub Actions workflow</p>
            </div>
        </body>
        </html>
        """
        return html
    
    def _create_text_email(self, jobs: List[Job]) -> str:
        """Create plain text email content"""
        text = f"New Job Opportunities Found!\n"
        text += f"Found {len(jobs)} new developer/internship roles in Abuja, Nigeria\n\n"
        text += "=" * 60 + "\n\n"
        
        for i, job in enumerate(jobs, 1):
            text += f"{i}. {job.title}\n"
            text += f"   Company: {job.company}\n"
            text += f"   Location: {job.location}\n"
            text += f"   Source: {job.source}\n"
            text += f"   Link: {job.url}\n\n"
        
        text += "=" * 60 + "\n"
        text += f"Job Monitor Bot | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        return text


class JobMonitor:
    """Main job monitoring orchestrator"""
    
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Override with environment variables if set
        self._load_env_overrides()
        
        self.scrapers = self._init_scrapers()
        self.notifier = EmailNotifier(self.config)
        self.seen_jobs_file = "seen_jobs.json"
        self.seen_jobs = self._load_seen_jobs()
    
    def _load_env_overrides(self):
        """Load config overrides from environment variables"""
        env_mapping = {
            'SENDER_EMAIL': ('email', 'sender_email'),
            'SENDER_PASSWORD': ('email', 'sender_password'),
            'RECIPIENT_EMAIL': ('email', 'recipient_email'),
        }
        
        for env_key, (section, key) in env_mapping.items():
            value = os.getenv(env_key)
            if value:
                self.config[section][key] = value
    
    def _init_scrapers(self) -> Dict[str, JobSiteScraper]:
        """Initialize enabled scrapers"""
        scrapers = {}
        site_config = self.config['job_sites']
        
        scraper_classes = {
            'linkedin': LinkedInScraper,
            'indeed': IndeedScraper,
            'jobberman': JobbermanScraper,
            'myjobmag': MyJobMagScraper,
            'ngcareers': NgCareersScraper,
            'hotnigerianjobs': HotNigerianJobsScraper,
        }
        
        for site, enabled in site_config.items():
            if enabled and site in scraper_classes:
                scrapers[site] = scraper_classes[site](self.config)
                logger.info(f"Initialized {site} scraper")
        
        return scrapers
    
    def _load_seen_jobs(self) -> set:
        """Load previously seen job URLs"""
        if os.path.exists(self.seen_jobs_file):
            try:
                with open(self.seen_jobs_file, 'r') as f:
                    data = json.load(f)
                    # Keep only last 30 days
                    cutoff = datetime.now() - timedelta(days=30)
                    filtered = {
                        url for url, timestamp in data.items()
                        if datetime.fromisoformat(timestamp) > cutoff
                    }
                    return filtered
            except Exception as e:
                logger.error(f"Error loading seen jobs: {e}")
        return set()
    
    def _save_seen_jobs(self):
        """Save seen job URLs with timestamps"""
        data = {url: datetime.now().isoformat() for url in self.seen_jobs}
        try:
            with open(self.seen_jobs_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving seen jobs: {e}")
    
    def _is_new_job(self, job: Job) -> bool:
        """Check if job is new (not seen before)"""
        # Create a unique identifier for the job
        job_id = f"{job.source}:{job.url}"
        return job_id not in self.seen_jobs
    
    def _mark_job_seen(self, job: Job):
        """Mark job as seen"""
        job_id = f"{job.source}:{job.url}"
        self.seen_jobs.add(job_id)
    
    def run_once(self) -> List[Job]:
        """Run one monitoring cycle"""
        logger.info("Starting job monitoring cycle...")
        
        all_new_jobs = []
        keywords = self.config['job_search']['keywords']
        exclude_keywords = self.config['job_search']['exclude_keywords']
        
        for site_name, scraper in self.scrapers.items():
            logger.info(f"Scraping {site_name}...")
            try:
                jobs = scraper.scrape()
                logger.info(f"Found {len(jobs)} jobs from {site_name}")
                
                # Filter jobs
                for job in jobs:
                    if job.matches_keywords(keywords, exclude_keywords):
                        if self._is_new_job(job):
                            all_new_jobs.append(job)
                            self._mark_job_seen(job)
                            logger.info(f"New job found: {job.title} at {job.company} ({job.source})")
                        else:
                            logger.debug(f"Already seen: {job.title}")
                    else:
                        logger.debug(f"Job didn't match keywords: {job.title}")
                        
            except Exception as e:
                logger.error(f"Error scraping {site_name}: {e}")
        
        # Save seen jobs
        self._save_seen_jobs()
        
        # Send notifications
        if all_new_jobs:
            logger.info(f"Sending notifications for {len(all_new_jobs)} new jobs")
            self.notifier.send_jobs(all_new_jobs)
        else:
            logger.info("No new matching jobs found")
        
        return all_new_jobs


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Job Monitor for Nigerian Job Sites')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--test-email', action='store_true', help='Send test email')
    args = parser.parse_args()
    
    monitor = JobMonitor(args.config)
    
    if args.test_email:
        # Send test email
        test_job = Job(
            title="Test Job - Software Developer Intern",
            company="Test Company",
            location="Abuja, Nigeria",
            url="https://example.com/job",
            source="Test"
        )
        monitor.notifier.send_jobs([test_job])
        return
    
    if args.once:
        monitor.run_once()
    else:
        # Run continuously (for local testing)
        interval = monitor.config['monitoring']['check_interval_minutes'] * 60
        logger.info(f"Starting continuous monitoring (every {interval/60} minutes)...")
        try:
            while True:
                monitor.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")


if __name__ == "__main__":
    main()