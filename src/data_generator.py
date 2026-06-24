"""
PHASE 1: Industrial Plant Data Generator
Generates realistic sensor data with compound risk scenarios
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import random
import os

class IndustrialPlantSimulator:
    """
    Simulates an industrial plant with multiple zones and sensors.
    Generates realistic data including normal operations and incident events.
    """
    
    def __init__(self):
        # Plant zones
        self.zones = ['Zone_A', 'Zone_B', 'Zone_C', 'Reactor_Area', 'Storage_Area']
        
        # Sensor configurations with realistic ranges
        self.sensors = {
            'gas_ppm': {'min': 0, 'max': 100, 'normal': (2, 8)},
            'temperature_c': {'min': 10, 'max': 120, 'normal': (75, 95)},
            'pressure_bar': {'min': 1, 'max': 8, 'normal': (4.5, 6.0)},
            'worker_count': {'min': 0, 'max': 12, 'normal': (3, 6)}
        }
        
        # Binary variables with probabilities
        self.binary_vars = {
            'maintenance_active': 0.08,   # 8% chance maintenance is happening
            'permit_active': 0.15          # 15% chance a permit is active
        }
    
    def generate_timestamp(self, base_time):
        """Generate sensor readings for a single timestamp"""
        data = {'timestamp': base_time}
        
        # Generate readings for each zone
        for zone in self.zones:
            for sensor, config in self.sensors.items():
                mean, std = config['normal']
                value = np.random.normal(mean, std * 0.3)
                value = np.clip(value, config['min'], config['max'])
                data[f'{zone}_{sensor}'] = round(value, 2)
            
            # Generate binary variables
            for var, prob in self.binary_vars.items():
                data[f'{zone}_{var}'] = 1 if random.random() < prob else 0
        
        # Shift change pattern (handover periods)
        data['shift_change'] = 1 if base_time.hour in [8, 16, 0] and base_time.minute < 30 else 0
        
        return data
    
    def inject_compound_risk(self, df, start_idx, duration=25):
        """
        Inject a compound risk scenario (like Visakhapatnam)
        Combines gas leak + maintenance activity
        """
        zone = random.choice(self.zones)
        
        # Gradual gas spike
        gas_values = np.linspace(15, 60, duration) + np.random.normal(0, 5, duration)
        gas_values = np.clip(gas_values, 0, 100)
        
        for i in range(duration):
            idx = start_idx + i
            if idx >= len(df):
                break
            
            # Increase gas levels
            df.at[idx, f'{zone}_gas_ppm'] = round(gas_values[i], 2)
            
            # Maintenance during the middle of the gas spike
            if duration//3 <= i <= 2*duration//3:
                df.at[idx, f'{zone}_maintenance_active'] = 1
                df.at[idx, f'{zone}_permit_active'] = 1
            
            # Workers present during incident
            if duration//4 <= i <= 3*duration//4:
                df.at[idx, f'{zone}_worker_count'] = np.random.randint(4, 8)
        
        return df
    
    def generate_data(self, days=30, interval_minutes=5):
        """
        Generate complete plant dataset
        
        Args:
            days: Number of days of data
            interval_minutes: Time between readings
        
        Returns:
            pandas.DataFrame: Complete dataset
        """
        total_points = int(days * 24 * 60 / interval_minutes)
        start_time = datetime.now() - timedelta(days=days)
        
        # Generate base data
        data = []
        for i in range(total_points):
            current_time = start_time + timedelta(minutes=i * interval_minutes)
            data.append(self.generate_timestamp(current_time))
        
        df = pd.DataFrame(data)
        
        # Inject 3 compound risk scenarios at different times
        for start in [total_points//5, total_points//2, 3*total_points//4]:
            df = self.inject_compound_risk(df, start)
        
        return df
    
    def save_data(self, df, filename='plant_data.csv'):
        """Save generated data to CSV"""
        os.makedirs('data', exist_ok=True)
        filepath = f'data/{filename}'
        df.to_csv(filepath, index=False)
        print(f"Data saved to {filepath}")
        print(f"Shape: {df.shape}")
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        return filepath


if __name__ == "__main__":
    print("Generating industrial plant data...")
    print("=" * 50)
    
    simulator = IndustrialPlantSimulator()
    df = simulator.generate_data(days=30, interval_minutes=5)
    simulator.save_data(df)
    
    print("\nData Preview:")
    print(df.head())
    print("\nColumn Summary:")
    print(df.describe())