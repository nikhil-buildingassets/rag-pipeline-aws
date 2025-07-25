import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List
from logger import logger
from cost_tracker import cost_tracker

class CostMonitor:
    """Monitors and analyzes OpenAI costs over time."""
    
    def __init__(self):
        self.daily_costs = {}
        self.monthly_costs = {}
        self.cost_alerts = []
    
    def add_session_costs(self, session_summary: Dict[str, Any], request_id: str = None):
        """Add session costs to daily and monthly tracking."""
        try:
            total_cost = session_summary['total_cost_usd']
            current_date = datetime.now()
            date_key = current_date.strftime('%Y-%m-%d')
            month_key = current_date.strftime('%Y-%m')
            
            # Update daily costs
            if date_key not in self.daily_costs:
                self.daily_costs[date_key] = {
                    'total_cost': 0.0,
                    'request_count': 0,
                    'api_calls': 0
                }
            
            self.daily_costs[date_key]['total_cost'] += total_cost
            self.daily_costs[date_key]['request_count'] += 1
            self.daily_costs[date_key]['api_calls'] += session_summary['total_api_calls']
            
            # Update monthly costs
            if month_key not in self.monthly_costs:
                self.monthly_costs[month_key] = {
                    'total_cost': 0.0,
                    'request_count': 0,
                    'api_calls': 0
                }
            
            self.monthly_costs[month_key]['total_cost'] += total_cost
            self.monthly_costs[month_key]['request_count'] += 1
            self.monthly_costs[month_key]['api_calls'] += session_summary['total_api_calls']
            
            # Check for cost alerts
            self._check_cost_alerts(total_cost, request_id)
            
            logger.info(f"Cost tracking updated - Date: {date_key}, "
                       f"Session Cost: ${total_cost:.6f}, "
                       f"Daily Total: ${self.daily_costs[date_key]['total_cost']:.6f}")
            
        except Exception as e:
            logger.error(f"Error adding session costs: {str(e)}")
    
    def _check_cost_alerts(self, session_cost: float, request_id: str = None):
        """Check for cost alerts and log warnings."""
        current_date = datetime.now()
        date_key = current_date.strftime('%Y-%m-%d')
        
        # Alert for high session cost (>$1.00)
        if session_cost > 1.00:
            alert = {
                'type': 'high_session_cost',
                'timestamp': current_date.isoformat(),
                'request_id': request_id,
                'cost': session_cost,
                'threshold': 1.00
            }
            self.cost_alerts.append(alert)
            logger.warning(f"High session cost alert: ${session_cost:.6f} for request {request_id}")
        
        # Alert for high daily cost (>$10.00)
        if date_key in self.daily_costs and self.daily_costs[date_key]['total_cost'] > 10.00:
            alert = {
                'type': 'high_daily_cost',
                'timestamp': current_date.isoformat(),
                'date': date_key,
                'cost': self.daily_costs[date_key]['total_cost'],
                'threshold': 10.00
            }
            self.cost_alerts.append(alert)
            logger.warning(f"High daily cost alert: ${self.daily_costs[date_key]['total_cost']:.6f} for {date_key}")
    
    def get_daily_summary(self, date: str = None) -> Dict[str, Any]:
        """Get cost summary for a specific date."""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        return self.daily_costs.get(date, {
            'total_cost': 0.0,
            'request_count': 0,
            'api_calls': 0
        })
    
    def get_monthly_summary(self, month: str = None) -> Dict[str, Any]:
        """Get cost summary for a specific month."""
        if month is None:
            month = datetime.now().strftime('%Y-%m')
        
        return self.monthly_costs.get(month, {
            'total_cost': 0.0,
            'request_count': 0,
            'api_calls': 0
        })
    
    def get_cost_trends(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get cost trends for the last N days."""
        trends = []
        current_date = datetime.now()
        
        for i in range(days):
            date = current_date - timedelta(days=i)
            date_key = date.strftime('%Y-%m-%d')
            daily_data = self.daily_costs.get(date_key, {
                'total_cost': 0.0,
                'request_count': 0,
                'api_calls': 0
            })
            
            trends.append({
                'date': date_key,
                'cost': daily_data['total_cost'],
                'requests': daily_data['request_count'],
                'api_calls': daily_data['api_calls']
            })
        
        return trends
    
    def log_cost_report(self):
        """Log a comprehensive cost report."""
        current_date = datetime.now()
        daily_summary = self.get_daily_summary()
        monthly_summary = self.get_monthly_summary()
        trends = self.get_cost_trends(7)
        
        logger.info("=== OpenAI Cost Report ===")
        logger.info(f"Date: {current_date.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Today's Cost: ${daily_summary['total_cost']:.6f}")
        logger.info(f"Today's Requests: {daily_summary['request_count']}")
        logger.info(f"Today's API Calls: {daily_summary['api_calls']}")
        logger.info(f"This Month's Cost: ${monthly_summary['total_cost']:.6f}")
        logger.info(f"This Month's Requests: {monthly_summary['request_count']}")
        
        logger.info("7-Day Trend:")
        for trend in trends:
            logger.info(f"  {trend['date']}: ${trend['cost']:.6f} ({trend['requests']} requests)")
        
        if self.cost_alerts:
            logger.info(f"Active Alerts: {len(self.cost_alerts)}")
            for alert in self.cost_alerts[-5:]:  # Show last 5 alerts
                logger.info(f"  {alert['type']}: ${alert['cost']:.6f}")
        
        logger.info("=" * 30)

# Global cost monitor instance
cost_monitor = CostMonitor() 