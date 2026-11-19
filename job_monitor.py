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
    # Enhanced fields
    requirements: Optional[List[str]] = None
    key_skills: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    experience_level: Optional[str] = None
    hiring_info: Optional[Dict[str, Any]] = None
    
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
    """Scrape LinkedIn Jobs with detailed analysis"""
    
    def scrape(self) -> List[Job]:
        jobs = []
        keywords = self.config['job_search']['keywords']
        location = self.config['job_search']['location']
        remote_keywords = self.config['job_search'].get('remote_keywords', [])
        
        # Search locations: Abuja + Remote
        search_locations = [location, "Remote"]
        
        # LinkedIn uses a specific URL structure for job search
        # We'll use the guest search API approach
        for keyword in keywords[:5]:  # Limit to first 5 keywords to avoid rate limiting
            for loc in search_locations:
                try:
                    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                    params = {
                        'keywords': keyword,
                        'location': loc,
                        'start': 0,
                    }
                    
                    soup = self._get_page_with_params(url, params)
                    if not soup:
                        continue
                    
                    job_cards = soup.find_all('li')
                    for card in job_cards[:self.config['monitoring']['max_jobs_per_site']]:
                        job = self._parse_job_card(card)
                        if job:
                            # Fetch detailed job info
                            self._enrich_job_details(job)
                            jobs.append(job)
                            
                except Exception as e:
                    logger.error(f"Error scraping LinkedIn for '{keyword}' in '{loc}': {e}")
        
        # Also search with remote-specific keywords in Abuja
        for remote_kw in remote_keywords[:3]:
            try:
                url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                params = {
                    'keywords': f"{remote_kw} developer",
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
                        self._enrich_job_details(job)
                        jobs.append(job)
                        
            except Exception as e:
                logger.error(f"Error scraping LinkedIn for remote kw '{remote_kw}': {e}")
        
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
    
    def _enrich_job_details(self, job: Job):
        """Fetch job detail page and extract requirements, keywords, certifications"""
        try:
            soup = self._get_page(job.url)
            if not soup:
                return
            
            # Get full job description
            desc_elem = soup.find('div', class_=re.compile(r'show-more-less-html__markup|description__text'))
            if not desc_elem:
                desc_elem = soup.find('section', class_=re.compile(r'description'))
            
            description = desc_elem.get_text(strip=True) if desc_elem else ""
            job.description = description[:5000]  # Limit size
            
            # Extract structured info
            job.requirements = self._extract_requirements(description)
            job.key_skills = self._extract_key_skills(description)
            job.certifications = self._extract_certifications(description)
            job.experience_level = self._extract_experience_level(description)
            job.job_type = self._extract_job_type(description)
            job.hiring_info = self._extract_hiring_info(soup, description)
            
        except Exception as e:
            logger.error(f"Error enriching job {job.url}: {e}")
    
    def _extract_requirements(self, text: str) -> List[str]:
        """Extract requirements from job description"""
        requirements = []
        text_lower = text.lower()
        
        # Common requirement patterns
        req_patterns = [
            r'(?:requirements?|qualifications?|what you.ll need|what we.re looking for)[:\s]*(.*?)(?:\n\n|\n[A-Z]|benefits?|we offer|$)',
            r'(?:must have|required|mandatory)[:\s]*([^.]+\.)',
        ]
        
        for pattern in req_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Split into bullet points
                items = re.split(r'[•\-\*\n]+', match)
                for item in items:
                    item = item.strip()
                    if len(item) > 20 and len(item) < 300:
                        requirements.append(item)
        
        return list(dict.fromkeys(requirements))[:10]  # Deduplicate, max 10
    
    def _extract_key_skills(self, text: str) -> List[str]:
        """Extract key technical skills mentioned"""
        skills = []
        text_lower = text.lower()
        
        # Common tech skills to look for
        tech_skills = [
            'python', 'javascript', 'typescript', 'java', 'c#', 'c++', 'go', 'rust', 'php', 'ruby',
            'react', 'vue', 'angular', 'next.js', 'nuxt', 'svelte',
            'node.js', 'express', 'django', 'flask', 'fastapi', 'spring', '.net',
            'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'terraform',
            'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch',
            'git', 'ci/cd', 'jenkins', 'github actions', 'gitlab',
            'rest api', 'graphql', 'grpc', 'microservices',
            'machine learning', 'ai', 'data science', 'pandas', 'numpy', 'tensorflow', 'pytorch',
        ]
        
        for skill in tech_skills:
            if skill in text_lower:
                skills.append(skill.title())
        
        return list(dict.fromkeys(skills))[:15]
    
    def _extract_certifications(self, text: str) -> List[str]:
        """Extract certification requirements"""
        certs = []
        text_lower = text.lower()
        
        cert_keywords = [
            'aws certified', 'azure certified', 'google cloud certified',
            'ckad', 'cka', 'ckad', 'cncf',
            'pmp', 'scrum master', 'csm', 'psm',
            'comptia', 'security+', 'network+',
            'cisco', 'ccna', 'ccnp', 'ccie',
            'oracle certified', 'microsoft certified',
            'itil', 'cobit', 'iso 27001',
            'certified', 'certification'
        ]
        
        for cert in cert_keywords:
            if cert in text_lower:
                # Find the context around it
                pattern = rf'.{{0,50}}{re.escape(cert)}.{{0,50}}'
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    certs.append(match.strip())
        
        return list(dict.fromkeys(certs))[:5]
    
    def _extract_experience_level(self, text: str) -> str:
        """Extract experience level"""
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in ['entry level', 'entry-level', 'junior', 'graduate', 'intern', 'trainee', '0-1 year', '0-2 years']):
            return "Entry/Junior"
        elif any(kw in text_lower for kw in ['senior', 'lead', 'principal', 'staff', '5+ years', '7+ years', '10+ years']):
            return "Senior"
        elif any(kw in text_lower for kw in ['mid', 'intermediate', '2-4 years', '3-5 years', '4-6 years']):
            return "Mid-level"
        return "Not specified"
    
    def _extract_job_type(self, text: str) -> str:
        """Extract job type"""
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in ['full.time', 'full-time', 'permanent']):
            return "Full-time"
        elif any(kw in text_lower for kw in ['contract', 'contractor', 'freelance']):
            return "Contract"
        elif any(kw in text_lower for kw in ['part.time', 'part-time']):
            return "Part-time"
        elif any(kw in text_lower for kw in ['intern', 'internship']):
            return "Internship"
        return "Not specified"
    
    def _extract_hiring_info(self, soup: BeautifulSoup, text: str) -> Dict[str, Any]:
        """Try to extract hiring team/contact info (limited on LinkedIn)"""
        info = {
            'hiring_manager': None,
            'team_members': [],
            'company_linkedin': None,
            'note': 'LinkedIn job postings rarely include direct contact emails. Connect via LinkedIn instead.'
        }
        
        # Try to find company LinkedIn URL
        company_link = soup.find('a', href=re.compile(r'linkedin\.com/company/'))
        if company_link:
            info['company_linkedin'] = company_link.get('href')
        
        # Look for "Posted by" or hiring team info
        posted_by = soup.find(string=re.compile(r'posted by|hiring team|recruiter', re.I))
        if posted_by:
            info['hiring_manager'] = posted_by.strip()[:200]
        
        return info


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
        remote_keywords = self.config['job_search'].get('remote_keywords', [])
        
        # Search locations: Abuja + Remote
        search_locations = ['abuja', 'remote']
        
        for keyword in keywords[:5]:
            for loc in search_locations:
                try:
                    url = "https://www.myjobmag.com/search/jobs"
                    params = {
                        'q': keyword,
                        'location': loc,
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
                    logger.error(f"Error scraping MyJobMag for '{keyword}' in '{loc}': {e}")
        
        # Also search with remote-specific keywords
        for remote_kw in remote_keywords[:3]:
            try:
                url = "https://www.myjobmag.com/search/jobs"
                params = {
                    'q': f"{remote_kw} developer",
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
                logger.error(f"Error scraping MyJobMag for remote kw '{remote_kw}': {e}")
        
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
        
        remote_count = sum(1 for j in jobs if getattr(j, 'job_type', '') == "remote")
        onsite_count = len(jobs) - remote_count
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            # Less spammy subject line
            msg['Subject'] = f"Job Alert: {len(jobs)} new opportunities ({onsite_count} Abuja, {remote_count} Remote)"
            # Professional From name
            msg['From'] = f"Job Monitor <{self.config['sender_email']}>"
            msg['To'] = self.config['recipient_email']
            # Anti-spam headers
            msg['List-Unsubscribe'] = f'<mailto:{self.config["sender_email"]}?subject=unsubscribe>'
            msg['Auto-Submitted'] = 'auto-generated'
            msg['Precedence'] = 'bulk'
            msg['X-Priority'] = '3'
            msg['X-MSMail-Priority'] = 'Normal'
            
            # Create HTML content
            html = self._create_html_email(jobs)
            text = self._create_text_email(jobs)
            
            msg.attach(MIMEText(text, 'plain', 'utf-8'))
            msg.attach(MIMEText(html, 'html', 'utf-8'))
            
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
        remote_count = sum(1 for j in jobs if getattr(j, 'job_type', '') == "remote")
        onsite_count = len(jobs) - remote_count
        
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
                .job-type-remote {{ display: inline-block; background: #10b981; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 10px; }}
                .job-type-onsite {{ display: inline-block; background: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 10px; }}
                .job-link {{ display: inline-block; background: #667eea; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; margin-top: 10px; }}
                .job-link:hover {{ background: #5568d3; }}
                .section {{ margin-top: 15px; padding-top: 10px; border-top: 1px solid #eee; }}
                .section-title {{ font-weight: bold; color: #667eea; margin-bottom: 8px; font-size: 14px; }}
                .skill-tag {{ display: inline-block; background: #e8f0fe; color: #1a73e8; padding: 3px 8px; border-radius: 12px; font-size: 11px; margin: 2px 4px 2px 0; }}
                .requirement {{ background: #fff3e0; padding: 8px 12px; border-radius: 4px; margin: 5px 0; font-size: 13px; border-left: 3px solid #ff9800; }}
                .cert {{ background: #e8f5e9; padding: 8px 12px; border-radius: 4px; margin: 5px 0; font-size: 13px; border-left: 3px solid #4caf50; }}
                .footer {{ text-align: center; padding: 20px; color: #888; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>[JOB ALERT] New Job Opportunities Found!</h1>
                <p>Found {len(jobs)} new developer/internship roles ({onsite_count} Abuja, {remote_count} Remote)</p>
            </div>
            <div class="content">
        """
        
        for job in jobs:
            job_type = getattr(job, 'job_type', 'onsite')
            type_badge = f'<span class="job-type-remote">🌍 Remote</span>' if job_type == "remote" else f'<span class="job-type-onsite">🏢 Abuja</span>'
            
            # Experience level badge
            exp_level = getattr(job, 'experience_level', 'Not specified')
            exp_badge = f'<span class="job-type-onsite">{exp_level}</span>'
            
            html += f"""
                <div class="job">
                    <div class="job-title">{job.title}</div>
                    <div class="job-company">[COMPANY] {job.company}</div>
                    <div class="job-location">[LOCATION] {job.location}</div>
                    {type_badge} {exp_badge}
                    <span class="job-source">{job.source}</span>
                    <a href="{job.url}" class="job-link" target="_blank">View Job →</a>
            """
            
            # Key Skills
            key_skills = getattr(job, 'key_skills', None)
            if key_skills:
                html += f"""
                    <div class="section">
                        <div class="section-title">🔑 Key Skills:</div>
                        {''.join(f'<span class="skill-tag">{skill}</span>' for skill in key_skills[:12])}
                    </div>
                """
            
            # Requirements
            requirements = getattr(job, 'requirements', None)
            if requirements:
                html += f"""
                    <div class="section">
                        <div class="section-title">📋 Requirements:</div>
                        {''.join(f'<div class="requirement">• {req}</div>' for req in requirements[:8])}
                    </div>
                """
            
            # Certifications
            certifications = getattr(job, 'certifications', None)
            if certifications:
                html += f"""
                    <div class="section">
                        <div class="section-title">📜 Certifications Mentioned:</div>
                        {''.join(f'<div class="cert">• {cert}</div>' for cert in certifications[:5])}
                    </div>
                """
            
            # Hiring info
            hiring_info = getattr(job, 'hiring_info', None)
            if hiring_info and hiring_info.get('company_linkedin'):
                html += f"""
                    <div class="section">
                        <div class="section-title">👥 Hiring Info:</div>
                        <div>Company LinkedIn: <a href="{hiring_info['company_linkedin']}" target="_blank">View Company</a></div>
                        <div style="color: #888; font-size: 12px; margin-top: 5px;">{hiring_info.get('note', '')}</div>
                    </div>
                """
            
            html += """
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
        remote_count = sum(1 for j in jobs if getattr(j, 'job_type', '') == "remote")
        onsite_count = len(jobs) - remote_count
        
        text = f"New Job Opportunities Found!\n"
        text += f"Found {len(jobs)} new developer/internship roles ({onsite_count} Abuja, {remote_count} Remote)\n\n"
        text += "=" * 60 + "\n\n"
        
        for i, job in enumerate(jobs, 1):
            job_type = getattr(job, 'job_type', 'onsite')
            type_str = "🌍 Remote" if job_type == "remote" else "🏢 Abuja"
            exp_level = getattr(job, 'experience_level', 'Not specified')
            
            text += f"{i}. {job.title}\n"
            text += f"   Company: {job.company}\n"
            text += f"   Location: {job.location}\n"
            text += f"   Type: {type_str} | Experience: {exp_level}\n"
            text += f"   Source: {job.source}\n"
            text += f"   Link: {job.url}\n"
            
            key_skills = getattr(job, 'key_skills', None)
            if key_skills:
                text += f"   Key Skills: {', '.join(key_skills[:10])}\n"
            
            requirements = getattr(job, 'requirements', None)
            if requirements:
                text += f"   Requirements:\n"
                for req in requirements[:5]:
                    text += f"     • {req}\n"
            
            certifications = getattr(job, 'certifications', None)
            if certifications:
                text += f"   Certifications: {', '.join(certifications[:3])}\n"
            
            hiring_info = getattr(job, 'hiring_info', None)
            if hiring_info and hiring_info.get('company_linkedin'):
                text += f"   Company LinkedIn: {hiring_info['company_linkedin']}\n"
            
            text += "\n"
        
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
    
    def _is_remote_job(self, job: Job) -> bool:
        """Check if job is remote based on location or keywords"""
        remote_keywords = self.config['job_search'].get('remote_keywords', [])
        text = f"{job.title} {job.location} {job.description or ''}".lower()
        for kw in remote_keywords:
            if kw.lower() in text:
                return True
        return False
    
    def run_once(self) -> List[Job]:
        """Run one monitoring cycle"""
        logger.info("Starting job monitoring cycle...")
        
        all_new_jobs = []
        keywords = self.config['job_search']['keywords']
        exclude_keywords = self.config['job_search']['exclude_keywords']
        remote_keywords = self.config['job_search'].get('remote_keywords', [])
        
        for site_name, scraper in self.scrapers.items():
            logger.info(f"Scraping {site_name}...")
            try:
                jobs = scraper.scrape()
                logger.info(f"Found {len(jobs)} jobs from {site_name}")
                
                # Filter jobs
                for job in jobs:
                    # Check if job matches main keywords
                    matches_main = job.matches_keywords(keywords, exclude_keywords)
                    
                    # Also check if it's a remote job (even if not in Abuja)
                    is_remote = self._is_remote_job(job)
                    matches_remote = is_remote and job.matches_keywords(keywords + remote_keywords, exclude_keywords)
                    
                    if matches_main or matches_remote:
                        # Set job type
                        job.job_type = "remote" if is_remote else "onsite"
                        
                        if self._is_new_job(job):
                            all_new_jobs.append(job)
                            self._mark_job_seen(job)
                            job_type_str = "🌍 Remote" if is_remote else "🏢 Onsite"
                            logger.info(f"New job found: {job.title} at {job.company} ({job.source}) [{job_type_str}]")
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
            remote_count = sum(1 for j in all_new_jobs if j.job_type == "remote")
            onsite_count = len(all_new_jobs) - remote_count
            logger.info(f"Sending notifications for {len(all_new_jobs)} new jobs ({onsite_count} Abuja, {remote_count} Remote)")
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