"""
PHASE 3: Interactive Heatmap Visualization
Creates color-coded map of plant safety risks
"""

import folium
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
import os


class PlantHeatmap:
    """
    Creates interactive heatmap of plant safety risks.
    Each zone is represented as a colored circle on the map.
    """
    
    def __init__(self, plant_coordinates: Optional[Dict] = None):
        # Default plant coordinates (plant floor grid coordinates centered at 0.0, 0.0)
        if plant_coordinates is None:
            self.plant_coordinates = {
                'Battery-1': {'lat': 0.004, 'lon': -0.015, 'width': 0.003, 'height': 0.006, 'label': 'Battery-1'},
                'Battery-2': {'lat': 0.004, 'lon': -0.010, 'width': 0.003, 'height': 0.006, 'label': 'Battery-2'},
                'Battery-3': {'lat': 0.004, 'lon': -0.005, 'width': 0.003, 'height': 0.006, 'label': 'Battery-3'},
                'Zone_A': {'lat': 0.004, 'lon': 0.000, 'width': 0.003, 'height': 0.006, 'label': 'Battery-4'},
                'Zone_B': {'lat': 0.004, 'lon': 0.005, 'width': 0.003, 'height': 0.006, 'label': 'Battery-5'},
                'Zone_C': {'lat': 0.004, 'lon': 0.010, 'width': 0.003, 'height': 0.006, 'label': 'Battery-6'},
                'Reactor_Area': {'lat': -0.004, 'lon': -0.010, 'width': 0.008, 'height': 0.005, 'label': 'Reactor Block'},
                'Control_Room': {'lat': -0.004, 'lon': -0.001, 'width': 0.004, 'height': 0.005, 'label': 'Control Room'},
                'Storage_Area': {'lat': -0.004, 'lon': 0.008, 'width': 0.007, 'height': 0.005, 'label': 'Storage Area'}
            }
        else:
            self.plant_coordinates = plant_coordinates
        
        # Risk level colors
        self.risk_colors = {
            'LOW': '#22c55e',
            'MEDIUM': '#eab308',
            'HIGH': '#f59e0b',
            'CRITICAL': '#ef4444'
        }
        
        self.risk_icons = {
            'LOW': '',
            'MEDIUM': '',
            'HIGH': '',
            'CRITICAL': ''
        }
        
        self.map = None
    
    def create_base_map(self, center_lat: float = 0.0, 
                        center_lon: float = -0.002) -> folium.Map:
        """Create the base map with plant boundary on a dark canvas"""
        self.map = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=16,
            tiles=None,
            control_scale=False,
            zoom_control=True,
            scrollWheelZoom=False,
            dragging=True
        )
        
        # Dark canvas background rectangle (covers the visible viewport area)
        folium.Rectangle(
            bounds=[[-90, -180], [90, 180]],
            fill=True,
            fill_color='#0a0e17',
            fill_opacity=1.0,
            color='#0a0e17',
            weight=0
        ).add_to(self.map)
        
        # Draw plant floor site boundary
        folium.Rectangle(
            bounds=[[-0.008, -0.018], [0.008, 0.014]],
            color='#3a3a4a',
            weight=2,
            fill=True,
            fill_color='#131b2b',
            fill_opacity=0.4,
            tooltip='SurakshaAI Plant Site'
        ).add_to(self.map)
        
        # Draw grid lines for schematic appearance
        for lat in np.linspace(-0.008, 0.008, 9):
            folium.PolyLine(
                locations=[[lat, -0.018], [lat, 0.014]],
                color='#2a2844',
                weight=1,
                opacity=0.3
            ).add_to(self.map)
        for lon in np.linspace(-0.018, 0.014, 15):
            folium.PolyLine(
                locations=[[-0.008, lon], [0.008, lon]],
                color='#2a2844',
                weight=1,
                opacity=0.3
            ).add_to(self.map)

        # Inject custom styling for Leaflet popups and markers into the map header
        custom_css = """
        <style>
        @keyframes folium-pulse {
            0% { transform: scale(0.6); opacity: 0.8; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
            70% { transform: scale(1.2); opacity: 0.3; box-shadow: 0 0 0 15px rgba(239, 68, 68, 0); }
            100% { transform: scale(0.6); opacity: 0; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
        }
        .pulsing-marker-critical {
            width: 24px;
            height: 24px;
            background: rgba(239, 68, 68, 0.35);
            border: 2px solid #ef4444;
            border-radius: 50%;
            animation: folium-pulse 1.4s infinite ease-out;
            pointer-events: none;
        }
        .pulsing-marker-high {
            width: 18px;
            height: 18px;
            background: rgba(245, 158, 11, 0.25);
            border: 2px solid #f59e0b;
            border-radius: 50%;
            animation: folium-pulse 1.8s infinite ease-out;
            pointer-events: none;
        }
        /* Custom Popup styling to match dark theme */
        .leaflet-popup-content-wrapper {
            background: #131b2b !important;
            color: #ffffff !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5) !important;
            padding: 2px !important;
        }
        .leaflet-popup-content {
            margin: 8px 10px !important;
        }
        .leaflet-popup-tip {
            background: #131b2b !important;
            border-left: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
        }
        .leaflet-popup-close-button {
            color: #a0b4c8 !important;
            padding: 8px 8px 0 0 !important;
        }
        .leaflet-popup-close-button:hover {
            color: #ffffff !important;
        }
        </style>
        """
        self.map.get_root().header.add_child(folium.Element(custom_css))
        
        return self.map
    
    def create_risk_zone(self, zone_name: str, risk_level: str, 
                          sensor_data: Dict) -> folium.Circle:
        """Create a colored circle risk zone with a centered text label"""
        coords = self.plant_coordinates[zone_name]
        color = self.risk_colors.get(risk_level, '#888888')
        
        # Calculate coordinate
        lat, lon = coords['lat'], coords['lon']
        
        label = coords.get('label', zone_name)
        popup_html = self._create_popup_html(label, risk_level, sensor_data)
        
        # Add pulsing marker for critical or high zones
        if risk_level == 'CRITICAL':
            folium.map.Marker(
                [lat, lon],
                icon=folium.DivIcon(
                    html='<div class="pulsing-marker-critical"></div>',
                    icon_size=(24, 24),
                    icon_anchor=(12, 12)
                )
            ).add_to(self.map)
        elif risk_level == 'HIGH':
            folium.map.Marker(
                [lat, lon],
                icon=folium.DivIcon(
                    html='<div class="pulsing-marker-high"></div>',
                    icon_size=(18, 18),
                    icon_anchor=(9, 9)
                )
            ).add_to(self.map)
            
        # Add text label in center using DivIcon, pointer-events: none allows clicking map under text
        folium.map.Marker(
            [lat, lon],
            icon=folium.DivIcon(
                html=f'<div style="font-family: \'Outfit\', sans-serif; font-size: 11px; font-weight: 700; color: #ffffff; text-align: center; width: 100px; transform: translate(-50%, -50%); text-shadow: 1px 1px 3px #000; pointer-events: none;">{label}</div>'
            )
        ).add_to(self.map)
        
        # Determine radius in meters based on scaling factor and coordinates
        radius = 28
        if risk_level == 'CRITICAL':
            radius = 42
        elif risk_level == 'HIGH':
            radius = 35
        elif risk_level == 'MEDIUM':
            radius = 30
            
        circle = folium.Circle(
            location=[lat, lon],
            radius=radius,
            color=color,
            weight=2 if risk_level in ['HIGH', 'CRITICAL'] else 1,
            fill=True,
            fill_color=color,
            fill_opacity=0.4 if risk_level in ['HIGH', 'CRITICAL'] else 0.15,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{label}: {risk_level}"
        )
        
        return circle
    
    def _create_popup_html(self, zone_name: str, risk_level: str, 
                           sensor_data: Dict) -> str:
        """Create HTML popup with sensor data"""
        color_hex = self.risk_colors.get(risk_level, '#a0b4c8')
        
        popup_html = f"""
        <div style="font-family: 'Outfit', sans-serif; min-width: 220px; padding: 4px; background: #131b2b; color: #ffffff;">
            <h4 style="margin: 0 0 6px 0; color: {color_hex}; font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">
                {zone_name}
            </h4>
            <div style="font-size: 11px; font-weight: 600; margin-bottom: 8px; color: #a0b4c8;">
                Risk State: <span style="color: {color_hex}; font-weight: 800;">{risk_level}</span>
            </div>
            <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 8px;">
                <table style="width: 100%; font-size: 11px; border-collapse: collapse; color: #a0b4c8;">
        """
        
        sensor_names = {
            'gas_ppm': 'Gas (ppm)',
            'temperature_c': 'Temperature (°C)',
            'pressure_bar': 'Pressure (bar)',
            'worker_count': 'Crew Members',
            'maintenance_active': 'Maintenance Status',
            'permit_active': 'Permit Status'
        }
        
        for col, value in sensor_data.items():
            sensor_key = col
            for prefix in [zone_name + '_', 'Zone_A_', 'Zone_B_', 'Zone_C_', 'Reactor_Area_', 'Storage_Area_', 'Battery-1_', 'Battery-2_', 'Battery-3_']:
                clean_prefix = prefix.replace(' ', '_').replace('-', '_')
                if col.startswith(prefix) or col.startswith(clean_prefix):
                    sensor_key = col[len(prefix):] if col.startswith(prefix) else col[len(clean_prefix):]
                    break
            
            display_name = sensor_names.get(sensor_key, sensor_key.replace('_', ' ').title())
            
            if isinstance(value, float):
                display_value = f"{value:.1f}"
            elif isinstance(value, int):
                display_value = "Yes" if sensor_key in ['maintenance_active', 'permit_active'] and value == 1 else "No" if sensor_key in ['maintenance_active', 'permit_active'] else str(value)
            else:
                display_value = str(value)
            
            color = '#ffffff'
            if 'gas' in sensor_key and isinstance(value, (int, float)) and value > 30:
                color = '#ef4444'
            elif 'temperature' in sensor_key and isinstance(value, (int, float)) and value > 90:
                color = '#f59e0b'
            
            popup_html += f"""
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
                <td style="padding: 4px 0; font-weight: 500;">{display_name}</td>
                <td style="padding: 4px 0; text-align: right; color: {color}; font-weight: 600;">{display_value}</td>
            </tr>
            """
        
        popup_html += f"""
                </table>
            </div>
            <div style="border-top: 1px solid rgba(255,255,255,0.08); margin-top: 8px; padding-top: 6px; font-size: 9px; color: #6b7d94; text-align: right;">
                Telemetry Refreshed
            </div>
        </div>
        """
        
        return popup_html
    
    def create_risk_heatmap(self, risk_data: Dict[str, Dict]) -> folium.Map:
        """Create complete heatmap from risk data"""
        self.create_base_map()
        
        for zone_name, data in risk_data.items():
            risk_level = data.get('risk_level', 'LOW')
            sensor_data = data.get('sensor_data', {})
            
            rect = self.create_risk_zone(zone_name, risk_level, sensor_data)
            rect.add_to(self.map)
        
        self.add_legend()
        return self.map
    
    def add_legend(self):
        """Add risk legend to the map"""
        legend_html = '''
        <div style="position: fixed; bottom: 15px; right: 15px; width: 130px; 
                    background: rgba(19, 27, 43, 0.9); backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; 
                    padding: 8px 10px; z-index: 9999; font-family: 'Outfit', sans-serif; font-size: 11px;
                    color: #ffffff; box-shadow: 0 4px 15px rgba(0,0,0,0.5);">
            <p style="margin: 0 0 6px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; font-size: 9px; color: #a0b4c8;">Risk Status</p>
            <div style="display: flex; align-items: center; margin-bottom: 4px;">
                <span style="display: inline-block; width: 10px; height: 10px; background: #ef4444; border-radius: 2px; margin-right: 6px;"></span>
                <span style="font-weight: 500;">Critical</span>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;">
                <span style="display: inline-block; width: 10px; height: 10px; background: #f59e0b; border-radius: 2px; margin-right: 6px;"></span>
                <span style="font-weight: 500;">High</span>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 4px;">
                <span style="display: inline-block; width: 10px; height: 10px; background: #eab308; border-radius: 2px; margin-right: 6px;"></span>
                <span style="font-weight: 500;">Medium</span>
            </div>
            <div style="display: flex; align-items: center;">
                <span style="display: inline-block; width: 10px; height: 10px; background: #22c55e; border-radius: 2px; margin-right: 6px;"></span>
                <span style="font-weight: 500;">Low</span>
            </div>
        </div>
        '''
        self.map.get_root().html.add_child(folium.Element(legend_html))

    
    def analyze_and_visualize(self, df: pd.DataFrame, engine, 
                              timestamp_index: int = -1) -> folium.Map:
        """Analyze data and create heatmap for a specific timestamp"""
        row = df.iloc[timestamp_index]
        alerts = engine.analyze_timestamp(row)
        
        risk_data = {}
        for zone in self.plant_coordinates.keys():
            zone_alert = next((a for a in alerts if a.zone == zone), None)
            
            if zone_alert:
                risk_data[zone] = {
                    'risk_level': zone_alert.risk_level,
                    'risk_score': zone_alert.risk_score,
                    'sensor_data': zone_alert.sensor_data
                }
            else:
                sensor_data = {}
                for col in row.index:
                    if zone in col:
                        sensor_data[col] = row[col]
                risk_data[zone] = {
                    'risk_level': 'LOW',
                    'risk_score': 0,
                    'sensor_data': sensor_data
                }
        
        self.create_risk_heatmap(risk_data)
        return self.map
    
    def save_heatmap(self, filename: str = 'heatmap.html'):
        """Save heatmap to HTML file"""
        os.makedirs('outputs', exist_ok=True)
        filepath = f'outputs/{filename}'
        if self.map is not None:
            self.map.save(filepath)
            print(f"Heatmap saved to {filepath}")
            return filepath
        else:
            print("No map to save")
            return None


if __name__ == "__main__":
    print("Testing Heatmap...")
    print("=" * 50)
    
    from risk_engine import CompoundRiskEngine
    
    # Load data
    df = pd.read_csv('data/plant_data.csv', parse_dates=['timestamp'])
    print(f"Loaded {len(df)} rows")
    
    # Initialize
    engine = CompoundRiskEngine()
    heatmap = PlantHeatmap()
    
    # Create heatmap for latest timestamp
    map_obj = heatmap.analyze_and_visualize(df, engine, timestamp_index=-1)
    heatmap.save_heatmap('heatmap_latest.html')
    
    print("\nHeatmap created!")
    print("Open outputs/heatmap_latest.html in your browser")