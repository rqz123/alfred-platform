"""
Dashboard service - provides aggregated statistics and insights.
"""

from datetime import datetime, timedelta
from typing import Dict, List
from storage.database import Database
from models.schema import DashboardStats


def _current_local_datetime() -> datetime:
    """Return the current local datetime for user-facing dashboard periods."""
    return datetime.now()


class DashboardService:
    """Service for dashboard statistics and analytics."""
    
    def __init__(self, database: Database):
        """
        Initialize dashboard service.
        
        Args:
            database: Database instance
        """
        self.db = database

    def get_period_bounds(self, period: str) -> tuple[datetime, datetime]:
        """Return start and end datetimes for the requested current period."""
        now = _current_local_datetime()

        if period == 'week':
            start = datetime.combine((now - timedelta(days=now.weekday())).date(), datetime.min.time())
        elif period == 'month':
            start = datetime(now.year, now.month, 1)
        elif period == 'year':
            start = datetime(now.year, 1, 1)
        else:
            raise ValueError(f"Unsupported period: {period}")

        end = now
        return start, end

    def get_period_dashboard(self, family_id: int, period: str) -> Dict:
        """Get dashboard summary and category analysis for the selected current period."""
        start_date, end_date = self.get_period_bounds(period)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COALESCE(SUM(total_amount), 0) AS total_amount,
                       COUNT(*) AS receipt_count,
                       COALESCE(AVG(total_amount), 0) AS average_amount
                FROM receipts
                WHERE family_id = ?
                AND DATE(purchase_date) BETWEEN ? AND ?
                  AND status = 'confirmed'
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            summary = dict(cursor.fetchone())

            cursor.execute("""
                SELECT category,
                       COALESCE(SUM(total_amount), 0) AS total,
                       COUNT(*) AS receipt_count
                FROM receipts
                WHERE family_id = ?
                                    AND DATE(purchase_date) BETWEEN ? AND ?
                  AND status = 'confirmed'
                GROUP BY category
                ORDER BY total DESC
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            category_rows = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT COALESCE(SUM(rd.amount), 0) AS total
                FROM receipt_deductions rd
                JOIN receipts r ON r.id = rd.receipt_id
                WHERE r.family_id = ?
                AND DATE(r.purchase_date) BETWEEN ? AND ?
                  AND r.status = 'confirmed'
                  AND rd.is_deductible = 1
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            deductible_total = cursor.fetchone()['total']

            cursor.execute("""
                SELECT r.id, r.merchant_name, r.purchase_date, r.total_amount,
                       r.category, u.username
                FROM receipts r
                JOIN users u ON u.id = r.user_id
                WHERE r.family_id = ?
                                    AND DATE(r.purchase_date) BETWEEN ? AND ?
                  AND r.status = 'confirmed'
                ORDER BY r.purchase_date DESC, r.created_at DESC
                LIMIT 10
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            recent_receipts = [dict(row) for row in cursor.fetchall()]

        category_breakdown = {row['category']: row['total'] for row in category_rows}
        top_category = category_rows[0]['category'] if category_rows else None
        top_category_amount = category_rows[0]['total'] if category_rows else 0.0

        return {
            'period': period,
            'start_date': start_date,
            'end_date': end_date,
            'total_amount': summary['total_amount'],
            'receipt_count': summary['receipt_count'],
            'average_amount': summary['average_amount'],
            'deductible_total': deductible_total,
            'category_breakdown': category_breakdown,
            'category_rows': category_rows,
            'top_category': top_category,
            'top_category_amount': top_category_amount,
            'recent_receipts': recent_receipts,
        }
    
    def get_family_dashboard(self, family_id: int) -> DashboardStats:
        """
        Get comprehensive dashboard statistics for a family.
        
        Args:
            family_id: Family identifier
            
        Returns:
            Dashboard statistics
        """
        now = _current_local_datetime()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Weekly expenses
            cursor.execute("""
                SELECT COALESCE(SUM(total_amount), 0) as total
                FROM receipts
                WHERE family_id = ? AND DATE(purchase_date) >= ? AND status = 'confirmed'
            """, (family_id, week_ago.date().isoformat()))
            total_week = cursor.fetchone()['total']
            
            # Monthly expenses
            cursor.execute("""
                SELECT COALESCE(SUM(total_amount), 0) as total
                FROM receipts
                WHERE family_id = ? AND DATE(purchase_date) >= ? AND status = 'confirmed'
            """, (family_id, month_ago.date().isoformat()))
            total_month = cursor.fetchone()['total']
            
            # Receipt counts
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM receipts
                WHERE family_id = ? AND DATE(purchase_date) >= ? AND status = 'confirmed'
            """, (family_id, week_ago.date().isoformat()))
            count_week = cursor.fetchone()['count']
            
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM receipts
                WHERE family_id = ? AND DATE(purchase_date) >= ? AND status = 'confirmed'
            """, (family_id, month_ago.date().isoformat()))
            count_month = cursor.fetchone()['count']
            
            # Category breakdown (month)
            cursor.execute("""
                SELECT category, COALESCE(SUM(total_amount), 0) as total
                FROM receipts
                WHERE family_id = ? AND DATE(purchase_date) >= ? AND status = 'confirmed'
                GROUP BY category
                ORDER BY total DESC
            """, (family_id, month_ago.date().isoformat()))
            category_breakdown = {row['category']: row['total'] for row in cursor.fetchall()}
            
            # Deductible amount (month)
            cursor.execute("""
                SELECT COALESCE(SUM(rd.amount), 0) as total
                FROM receipt_deductions rd
                JOIN receipts r ON r.id = rd.receipt_id
                                WHERE r.family_id = ? AND DATE(r.purchase_date) >= ? 
                  AND r.status = 'confirmed' AND rd.is_deductible = 1
            """, (family_id, month_ago.date().isoformat()))
            deductible_month = cursor.fetchone()['total']
            
            # Recent receipts
            cursor.execute("""
                SELECT r.id, r.merchant_name, r.purchase_date, r.total_amount, 
                       r.category, u.username
                FROM receipts r
                JOIN users u ON u.id = r.user_id
                WHERE r.family_id = ? AND r.status = 'confirmed'
                ORDER BY r.purchase_date DESC
                LIMIT 10
            """, (family_id,))
            recent_receipts = [dict(row) for row in cursor.fetchall()]
        
        return DashboardStats(
            total_expenses_week=total_week,
            total_expenses_month=total_month,
            category_breakdown=category_breakdown,
            deductible_amount_month=deductible_month,
            receipt_count_week=count_week,
            receipt_count_month=count_month,
            recent_receipts=recent_receipts
        )
    
    def get_deduction_summary(
        self,
        family_id: int,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict:
        """
        Get tax deduction summary for specified period.
        
        Args:
            family_id: Family identifier
            start_date: Start date (defaults to 30 days ago)
            end_date: End date (defaults to now)
            
        Returns:
            Dictionary with deduction summary
        """
        if not start_date:
            start_date = _current_local_datetime() - timedelta(days=30)
        if not end_date:
            end_date = _current_local_datetime()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Summary by deduction type
            cursor.execute("""
                SELECT rd.deduction_type, rd.evidence_level,
                       COUNT(*) as count, COALESCE(SUM(rd.amount), 0) as total
                FROM receipt_deductions rd
                JOIN receipts r ON r.id = rd.receipt_id
                                WHERE r.family_id = ? AND DATE(r.purchase_date) BETWEEN ? AND ?
                  AND r.status = 'confirmed' AND rd.is_deductible = 1
                GROUP BY rd.deduction_type, rd.evidence_level
                ORDER BY total DESC
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            
            by_type = {}
            for row in cursor.fetchall():
                dtype = row['deduction_type']
                if dtype not in by_type:
                    by_type[dtype] = {
                        'total_amount': 0,
                        'count': 0,
                        'by_evidence': {}
                    }
                by_type[dtype]['total_amount'] += row['total']
                by_type[dtype]['count'] += row['count']
                by_type[dtype]['by_evidence'][row['evidence_level']] = {
                    'count': row['count'],
                    'amount': row['total']
                }
            
            # Detailed items
            cursor.execute("""
                SELECT r.id, r.merchant_name, r.purchase_date, r.total_amount,
                       rd.deduction_type, rd.evidence_level, rd.evidence_text
                FROM receipts r
                JOIN receipt_deductions rd ON rd.receipt_id = r.id
                                WHERE r.family_id = ? AND DATE(r.purchase_date) BETWEEN ? AND ?
                  AND r.status = 'confirmed' AND rd.is_deductible = 1
                ORDER BY r.purchase_date DESC
            """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            
            items = [dict(row) for row in cursor.fetchall()]
            
            return {
                'summary_by_type': by_type,
                'total_deductible': sum(t['total_amount'] for t in by_type.values()),
                'total_items': sum(t['count'] for t in by_type.values()),
                'items': items,
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                }
            }
    
    def get_spending_trends(
        self,
        family_id: int,
        days: int = 30,
        group_by: str = 'day',
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> List[Dict]:
        """
        Get spending trends over time.
        
        Args:
            family_id: Family identifier
            days: Number of days to look back
            group_by: Grouping period ('day' or 'week')
            
        Returns:
            List of trend data points
        """
        if start_date is None:
            start_date = _current_local_datetime() - timedelta(days=days)
        if end_date is None:
            end_date = _current_local_datetime()
        
        if group_by == 'day':
            group_expr = "DATE(purchase_date)"
        else:  # week
            group_expr = "strftime('%Y-%W', purchase_date)"
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT {group_expr} as period,
                       COALESCE(SUM(total_amount), 0) as total,
                       COUNT(*) as count
                FROM receipts
                                WHERE family_id = ?
                                    AND DATE(purchase_date) BETWEEN ? AND ?
                                    AND status = 'confirmed'
                GROUP BY {group_expr}
                ORDER BY period ASC
                        """, (family_id, start_date.date().isoformat(), end_date.date().isoformat()))
            
            return [dict(row) for row in cursor.fetchall()]
