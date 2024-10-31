import pyzill
import json
import time
import urllib.parse
from typing import List, Dict, Any
import random
from datetime import datetime

class ZillowScraper:
    def __init__(self, wait_time_range=(2, 5)):
        self.wait_time_range = wait_time_range
        self.categories = ['for_sale', 'for_rent', 'sold']
        self.MAX_RESULTS_PER_QUERY = 500
        self.MIN_ZOOM_LEVEL = 15  # Minimum zoom level for detailed results

    def extract_map_bounds_from_url(self, url: str) -> Dict[str, float]:
        """
        Extract map bounds and zoom level from Zillow URL
        
        Args:
            url: Zillow search URL
            
        Returns:
            Dictionary containing coordinate bounds and zoom level
        """
        try:
            # Extract the searchQueryState parameter from the URL
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            # Get the searchQueryState JSON string and parse it
            search_query_state = json.loads(urllib.parse.unquote(query_params['searchQueryState'][0]))
            
            # Extract map bounds
            map_bounds = search_query_state['mapBounds']
            
            # Extract zoom level
            zoom_value = search_query_state.get('mapZoom', 13)  # Default to 13 if not present
            
            return {
                'ne_lat': map_bounds['north'],
                'ne_long': map_bounds['east'],
                'sw_lat': map_bounds['south'],
                'sw_long': map_bounds['west'],
                'zoom': zoom_value
            }
        except Exception as e:
            print(f"Error parsing URL: {e}")
            return None
        
    def calculate_zoom_sections(self, ne_lat: float, ne_long: float, 
                              sw_lat: float, sw_long: float, 
                              initial_zoom: int) -> List[Dict]:
        """
        Calculate sections with appropriate zoom levels to cover the entire area
        """
        # Calculate area size
        lat_distance = abs(ne_lat - sw_lat)
        long_distance = abs(ne_long - sw_long)
        
        # Calculate number of sections needed
        # At zoom level 15, each section should be roughly 0.01 degrees square
        sections_lat = max(1, int(lat_distance / 0.01))
        sections_long = max(1, int(long_distance / 0.01))
        
        lat_step = lat_distance / sections_lat
        long_step = long_distance / sections_long
        
        sections = []
        
        for i in range(sections_lat):
            for j in range(sections_long):
                section = {
                    'ne_lat': sw_lat + (i + 1) * lat_step,
                    'sw_lat': sw_lat + i * lat_step,
                    'ne_long': sw_long + (j + 1) * long_step,
                    'sw_long': sw_long + j * long_step,
                    'zoom': self.MIN_ZOOM_LEVEL
                }
                sections.append(section)
                
        print(f"Area divided into {len(sections)} sections at zoom level {self.MIN_ZOOM_LEVEL}")
        return sections

    def wait_random_time(self):
        """Wait for a random amount of time between requests"""
        time.sleep(random.uniform(*self.wait_time_range))

    def get_results_for_box(self, box: Dict[str, float], zoom_value: int, 
                           category: str = 'for_sale', proxy_url: str = None) -> List[Dict]:
        """
        Get results for a single section
        """
        try:
            if category == 'for_sale':
                results = pyzill.for_sale(1, box['ne_lat'], box['ne_long'], 
                                        box['sw_lat'], box['sw_long'], 
                                        zoom_value, proxy_url)
            elif category == 'for_rent':
                results = pyzill.for_rent(1, box['ne_lat'], box['ne_long'], 
                                        box['sw_lat'], box['sw_long'], 
                                        zoom_value, proxy_url)
            elif category == 'sold':
                results = pyzill.sold(1, box['ne_lat'], box['ne_long'], 
                                    box['sw_lat'], box['sw_long'], 
                                    zoom_value, proxy_url)

            map_results = results.get('mapResults', [])
            if len(map_results) >= self.MAX_RESULTS_PER_QUERY * 0.9:  # 90% of max
                print(f"Warning: Section might be hitting result limit ({len(map_results)} results)")
                
            return map_results
        except Exception as e:
            print(f"Error fetching results for {category} in section: {e}")
            return []

    def get_all_results(self, ne_lat: float, ne_long: float, sw_lat: float, 
                       sw_long: float, initial_zoom: int, proxy_url: str = None) -> Dict[str, List[Dict]]:
        """
        Get results for all categories with automatic zooming and sectioning
        """
        print("\nCalculating optimal coverage for the area...")
        sections = self.calculate_zoom_sections(ne_lat, ne_long, sw_lat, sw_long, initial_zoom)
        
        all_results = {category: [] for category in self.categories}
        
        total_sections = len(sections)
        for i, section in enumerate(sections, 1):
            print(f"\nProcessing section {i}/{total_sections}")
            print(f"Coordinates: ({section['ne_lat']:.6f}, {section['ne_long']:.6f}) to "
                  f"({section['sw_lat']:.6f}, {section['sw_long']:.6f})")
            
            for category in self.categories:
                print(f"Fetching {category} listings...")
                results = self.get_results_for_box(section, section['zoom'], category, proxy_url)
                if results:
                    print(f"Found {len(results)} {category} listings in this section")
                    all_results[category].extend(results)
                else:
                    print(f"No {category} listings found in this section")
                self.wait_random_time()
        
        # Remove duplicates
        print("\nRemoving duplicates...")
        for category in self.categories:
            initial_count = len(all_results[category])
            seen_zpids = set()
            unique_results = []
            for result in all_results[category]:
                zpid = result.get('zpid')
                if zpid and zpid not in seen_zpids:
                    seen_zpids.add(zpid)
                    unique_results.append(result)
            all_results[category] = unique_results
            final_count = len(unique_results)
            print(f"{category}: {initial_count} total listings, {final_count} unique listings "
                  f"({initial_count - final_count} duplicates removed)")
            
        return all_results

    def save_results(self, results: Dict[str, List[Dict]], base_filename: str):
        """
        Save results for each category to separate JSON files
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save individual category files
        for category in self.categories:
            try:
                filename = f"{base_filename}_{category}_{timestamp}.json"
                with open(filename, 'w') as f:
                    json.dump(results[category], f, indent=2)
                print(f"Successfully saved {category} results to {filename}")
                print(f"Total {category} listings: {len(results[category])}")
            except Exception as e:
                print(f"Error saving {category} results: {e}")
        
        # Save combined results
        try:
            combined_filename = f"{base_filename}_all_{timestamp}.json"
            with open(combined_filename, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Successfully saved combined results to {combined_filename}")
        except Exception as e:
            print(f"Error saving combined results: {e}")

def main():
    # Initialize scraper
    scraper = ZillowScraper(wait_time_range=(3, 7))
    
    # Get URL from user
    url = input("Please enter the Zillow URL: ")
    
    # Extract parameters from URL
    params = scraper.extract_map_bounds_from_url(url)
    if not params:
        print("Failed to extract parameters from URL")
        return
    
    try:
        print("\nStarting comprehensive area coverage...")
        print(f"Original zoom level: {params['zoom']}")
        print(f"Area coordinates: ({params['ne_lat']:.6f}, {params['ne_long']:.6f}) to "
              f"({params['sw_lat']:.6f}, {params['sw_long']:.6f})")
        
        # Get results with automatic zooming and sectioning
        results = scraper.get_all_results(
            params['ne_lat'],
            params['ne_long'],
            params['sw_lat'],
            params['sw_long'],
            params['zoom']
        )
        
        # Calculate total results
        total_listings = sum(len(results[category]) for category in scraper.categories)
        print(f"\nTotal unique listings found across all categories: {total_listings}")
        for category in scraper.categories:
            print(f"{category}: {len(results[category])} listings")
        
        # Save results
        location_name = url.split('/')[3].split('?')[0]
        base_filename = f"zillow_{location_name}"
        scraper.save_results(results, base_filename)
        
    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == "__main__":
    main()