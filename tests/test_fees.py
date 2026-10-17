from skibasar.fees import FeeRules, settle

RULES = FeeRules(offer_fee_cents=200, commission_bp=1000)


def test_fee_open_is_deducted():
    s = settle([6000, 4000], RULES, fee_exempt=False, offer_fee_paid_at_entry=False)
    assert (s.sold_total_cents, s.commission_cents, s.open_offer_fee_cents) == (10000, 1000, 200)
    assert s.payout_cents == 8800
    assert not s.seller_pays


def test_fee_paid_at_entry_not_deducted():
    s = settle([6000, 4000], RULES, fee_exempt=False, offer_fee_paid_at_entry=True)
    assert s.payout_cents == 9000


def test_exempt_pays_nothing():
    s = settle([6000], RULES, fee_exempt=True, offer_fee_paid_at_entry=False)
    assert (s.commission_cents, s.open_offer_fee_cents, s.payout_cents) == (0, 0, 6000)


def test_nothing_sold_with_open_fee_seller_pays():
    s = settle([], RULES, fee_exempt=False, offer_fee_paid_at_entry=False)
    assert s.payout_cents == -200
    assert s.seller_pays


def test_commission_on_total_not_per_article():
    # Per article: 3 x round(0,5 ct) = 3 ct; on total 15 ct -> 1,5 ct -> 2 ct.
    s = settle([5, 5, 5], FeeRules(0, 1000), fee_exempt=False, offer_fee_paid_at_entry=True)
    assert s.commission_cents == 2


def test_identity_holds():
    s = settle(
        [1999, 2999, 49], FeeRules(250, 1250), fee_exempt=False, offer_fee_paid_at_entry=False
    )
    assert s.payout_cents + s.commission_cents + s.open_offer_fee_cents == s.sold_total_cents
