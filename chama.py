# chama.py - Chama automation routes
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
from functools import wraps
from db import query, execute
import secrets
import time

chama_bp = Blueprint('chama', __name__, url_prefix='/chama')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_share_code():
    """Generate unique share code for chama group"""
    while True:
        code = secrets.token_hex(4).upper()
        existing = query("SELECT id FROM chama_groups WHERE share_code=?", (code,), one=True)
        if not existing:
            return code

# ============== CHAMA GROUP MANAGEMENT ==============

@chama_bp.route('/')
@login_required
def dashboard():
    """User's chama dashboard"""
    # Groups user leads
    leading = query("SELECT * FROM chama_groups WHERE leader_id=?", (g.user['id'],))
    
    # Groups user is member of
    membership = query("""
        SELECT cg.*, cm.current_balance, cm.total_contributed
        FROM chama_members cm
        JOIN chama_groups cg ON cm.group_id = cg.id
        WHERE cm.user_id=? AND cm.is_active=1
    """, (g.user['id'],))
    
    # Pending loan requests (if user is leader)
    pending_loans = []
    if leading:
        placeholders = ','.join(['?'] * len(leading))
        pending_loans = query(f"""
            SELECT cl.*, u.username, cg.name as group_name
            FROM chama_loans cl
            JOIN chama_groups cg ON cl.group_id = cg.id
            JOIN users u ON cl.member_id = u.id
            WHERE cl.status='pending' AND cg.leader_id=?
        """, (g.user['id'],))
    
    return render_template('chama/dashboard.html', 
                          leading=leading, 
                          membership=membership,
                          pending_loans=pending_loans,
                          user=g.user)

@chama_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_group():
    """Create a new chama group"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        contribution = float(request.form.get('contribution', 0))
        frequency = request.form.get('frequency', 'weekly')
        payout_cycle = request.form.get('payout_cycle', 'monthly')
        interest_rate = float(request.form.get('interest_rate', 0))
        
        if not name or contribution < 10:
            flash('Group name and minimum contribution required.', 'danger')
            return render_template('chama/create.html')
        
        share_code = generate_share_code()
        
        group_id = execute("""
            INSERT INTO chama_groups 
            (name, leader_id, contribution_amount, contribution_frequency, 
             payout_cycle, interest_rate, share_code)
            VALUES (?,?,?,?,?,?,?)
        """, (name, g.user['id'], contribution, frequency, payout_cycle, interest_rate, share_code))
        
        # Add leader as first member
        execute("""
            INSERT INTO chama_members (group_id, user_id)
            VALUES (?,?)
        """, (group_id, g.user['id']))
        
        flash(f'Chama group "{name}" created! Share code: {share_code}', 'success')
        return redirect(url_for('chama.dashboard'))
    
    return render_template('chama/create.html', user=g.user)

@chama_bp.route('/join', methods=['POST'])
@login_required
def join_group():
    """Join a chama group using share code"""
    share_code = request.form.get('share_code', '').strip().upper()
    
    group = query("SELECT * FROM chama_groups WHERE share_code=? AND is_active=1", (share_code,), one=True)
    if not group:
        flash('Invalid share code.', 'danger')
        return redirect(url_for('chama.dashboard'))
    
    # Check if already member
    existing = query("SELECT id FROM chama_members WHERE group_id=? AND user_id=?", 
                    (group['id'], g.user['id']), one=True)
    if existing:
        flash('You are already a member of this chama.', 'warning')
        return redirect(url_for('chama.dashboard'))
    
    execute("INSERT INTO chama_members (group_id, user_id) VALUES (?,?)", 
            (group['id'], g.user['id']))
    
    flash(f'You have joined "{group["name"]}"!', 'success')
    return redirect(url_for('chama.dashboard'))

# ============== CONTRIBUTIONS & STK PUSH ==============

@chama_bp.route('/group/<int:group_id>')
@login_required
def group_detail(group_id):
    """View group details and contribute"""
    group = query("SELECT * FROM chama_groups WHERE id=?", (group_id,), one=True)
    if not group:
        flash('Group not found.', 'danger')
        return redirect(url_for('chama.dashboard'))
    
    # Check if user is member
    membership = query("SELECT * FROM chama_members WHERE group_id=? AND user_id=?", 
                      (group_id, g.user['id']), one=True)
    if not membership and group['leader_id'] != g.user['id']:
        flash('You are not a member of this group.', 'danger')
        return redirect(url_for('chama.dashboard'))
    
    members = query("""
        SELECT u.username, cm.current_balance, cm.total_contributed, cm.joined_at
        FROM chama_members cm
        JOIN users u ON cm.user_id = u.id
        WHERE cm.group_id=? AND cm.is_active=1
    """, (group_id,))
    
    contributions = query("""
        SELECT * FROM chama_contributions 
        WHERE group_id=? AND member_id=? 
        ORDER BY created_at DESC LIMIT 20
    """, (group_id, g.user['id']))
    
    loans = query("SELECT * FROM chama_loans WHERE group_id=? AND member_id=?", 
                  (group_id, g.user['id']))
    
    return render_template('chama/group_detail.html',
                          group=group, members=members, 
                          contributions=contributions, loans=loans,
                          user=g.user, membership=membership)

@chama_bp.route('/group/<int:group_id>/contribute', methods=['POST'])
@login_required
def contribute(group_id):
    """Initiate STK Push for contribution"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    phone = data.get('phone', g.user.get('phone', ''))
    
    group = query("SELECT * FROM chama_groups WHERE id=?", (group_id,), one=True)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    
    if amount < group['contribution_amount']:
        return jsonify({'error': f'Minimum contribution is {group["contribution_amount"]} KES'}), 400
    
    # Generate reference
    ref = f"CHM_{group_id}_{g.user['id']}_{int(time.time())}"
    
    # Create pending contribution record
    execute("""
        INSERT INTO chama_contributions (group_id, member_id, amount, transaction_ref, status)
        VALUES (?,?,?,?,?)
    """, (group_id, g.user['id'], amount, ref, 'pending'))
    
    # Here you would call IntaSend/PesaPal STK Push
    # For now, simulate response
    return jsonify({
        'success': True,
        'message': 'STK Push sent. Check your phone.',
        'reference': ref
    })

@chama_bp.route('/api/ipn/chama', methods=['POST'])
def chama_ipn():
    """Webhook for payment confirmation"""
    data = request.get_json()
    transaction_ref = data.get('reference', '')
    status = data.get('status', '')
    
    if status == 'completed' and transaction_ref.startswith('CHM_'):
        # Update contribution status
        execute("UPDATE chama_contributions SET status='confirmed' WHERE transaction_ref=?", (transaction_ref,))
        
        # Get contribution details
        contrib = query("SELECT * FROM chama_contributions WHERE transaction_ref=?", (transaction_ref,), one=True)
        if contrib:
            # Update member balance
            execute("""
                UPDATE chama_members 
                SET current_balance = current_balance + ?,
                    total_contributed = total_contributed + ?
                WHERE group_id=? AND user_id=?
            """, (contrib['amount'], contrib['amount'], contrib['group_id'], contrib['member_id']))
            
            # Update group total balance
            execute("UPDATE chama_groups SET total_balance = total_balance + ? WHERE id=?", 
                   (contrib['amount'], contrib['group_id']))
    
    return 'OK', 200

# ============== LOANS ==============

@chama_bp.route('/group/<int:group_id>/loan/request', methods=['POST'])
@login_required
def request_loan(group_id):
    """Request a loan from the chama"""
    data = request.get_json()
    amount = float(data.get('amount', 0))
    
    group = query("SELECT * FROM chama_groups WHERE id=?", (group_id,), one=True)
    membership = query("SELECT * FROM chama_members WHERE group_id=? AND user_id=?", 
                      (group_id, g.user['id']), one=True)
    
    if not membership:
        return jsonify({'error': 'Not a member'}), 403
    
    max_loan = membership['current_balance'] * 3
    if amount > max_loan:
        return jsonify({'error': f'Maximum loan is {max_loan} KES (3x your balance)'}), 400
    
    if amount > group['total_balance']:
        return jsonify({'error': 'Insufficient group funds'}), 400
    
    interest = amount * (group['interest_rate'] / 100)
    due_date = time.strftime('%Y-%m-%d', time.localtime(time.time() + 30*86400))
    
    execute("""
        INSERT INTO chama_loans 
        (group_id, member_id, amount, interest_rate, due_date)
        VALUES (?,?,?,?,?)
    """, (group_id, g.user['id'], amount, group['interest_rate'], due_date))
    
    flash('Loan request submitted. Awaiting approval.', 'success')
    return jsonify({'success': True})

@chama_bp.route('/loan/<int:loan_id>/approve', methods=['POST'])
@login_required
def approve_loan(loan_id):
    """Approve a loan request (leader only)"""
    loan = query("""
        SELECT cl.*, cg.leader_id, cg.id as group_id
        FROM chama_loans cl
        JOIN chama_groups cg ON cl.group_id = cg.id
        WHERE cl.id=?
    """, (loan_id,), one=True)
    
    if not loan or loan['leader_id'] != g.user['id']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('chama.dashboard'))
    
    # Update loan status
    execute("""
        UPDATE chama_loans 
        SET status='approved', approved_by=?, approved_at=datetime('now')
        WHERE id=?
    """, (g.user['id'], loan_id))
    
    # Disburse to member
    execute("""
        UPDATE chama_members 
        SET current_balance = current_balance + ?
        WHERE group_id=? AND user_id=?
    """, (loan['amount'], loan['group_id'], loan['member_id']))
    
    # Decrease group balance
    execute("UPDATE chama_groups SET total_balance = total_balance - ? WHERE id=?", 
           (loan['amount'], loan['group_id']))
    
    flash('Loan approved and disbursed.', 'success')
    return redirect(url_for('chama.group_detail', group_id=loan['group_id']))

@chama_bp.route('/loan/<int:loan_id>/repay', methods=['POST'])
@login_required
def repay_loan(loan_id):
    """Repay a loan via STK Push"""
    loan = query("SELECT * FROM chama_loans WHERE id=? AND member_id=?", 
                (loan_id, g.user['id']), one=True)
    
    if not loan or loan['status'] != 'approved':
        return jsonify({'error': 'Invalid loan'}), 400
    
    data = request.get_json()
    amount = float(data.get('amount', loan['amount']))
    
    # Process repayment logic
    # (STK Push integration here)
    
    return jsonify({'success': True, 'message': 'Repayment initiated'})
