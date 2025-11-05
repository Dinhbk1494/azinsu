#!/usr/bin/env python3
"""
Test script to compare old vs improved disease checker
"""

import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_disease_checker import check_drug_list_by_multi_diseases_ilike as old_checker
from simple_disease_checker_improved import check_drug_list_by_multi_diseases_ilike as new_checker

async def test_disease_matching():
    """Test disease matching with various examples"""
    
    database_url = "postgresql://postgres.jhxutciiidfpnhbnmyjc:Motconvit131294@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    
    test_cases = [
        {
            "diagnosis": "Viêm họng cấp tính",
            "drugs": ["Paracetamol", "Amoxicillin", "Cetirizine"],
            "expected_diseases": ["viêm họng"]
        },
        {
            "diagnosis": "Viêm tai giữa bên trái",
            "drugs": ["Ileffexime", "Paracetamol"],
            "expected_diseases": ["viêm tai"]
        },
        {
            "diagnosis": "Viêm mũi dị ứng kèm hen suyễn",
            "drugs": ["Desloratadin", "Salbutamol"],
            "expected_diseases": ["viêm mũi", "hen suyễn"]
        },
        {
            "diagnosis": "Viêm dạ dày cấp tính",
            "drugs": ["Omeprazole", "Metronidazole"],
            "expected_diseases": ["viêm dạ dày"]
        }
    ]
    
    print("=" * 80)
    print("TESTING DISEASE MATCHING: OLD vs IMPROVED SYSTEM")
    print("=" * 80)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🔍 TEST CASE {i}: {test_case['diagnosis']}")
        print(f"Drugs: {test_case['drugs']}")
        print(f"Expected diseases: {test_case['expected_diseases']}")
        print("-" * 60)
        
        try:
            # Test old system
            print("📊 OLD SYSTEM:")
            old_result = await old_checker(test_case['diagnosis'], test_case['drugs'], database_url)
            print(f"  Diseases found: {old_result['diseases']}")
            for result in old_result['results']:
                print(f"  {result['input_name']}: {result['role']} - {result['related_diseases']}")
            
            # Test new system
            print("\n📊 IMPROVED SYSTEM:")
            new_result = await new_checker(test_case['diagnosis'], test_case['drugs'], database_url)
            print(f"  Diseases found: {new_result['diseases']}")
            for result in new_result['results']:
                print(f"  {result['input_name']}: {result['role']} - {result['related_diseases']}")
            
            # Compare results
            print("\n📈 COMPARISON:")
            old_diseases = set(old_result['diseases'])
            new_diseases = set(new_result['diseases'])
            expected_diseases = set(test_case['expected_diseases'])
            
            print(f"  Old system diseases: {old_diseases}")
            print(f"  New system diseases: {new_diseases}")
            print(f"  Expected diseases: {expected_diseases}")
            
            old_accuracy = len(old_diseases.intersection(expected_diseases)) / len(expected_diseases) if expected_diseases else 0
            new_accuracy = len(new_diseases.intersection(expected_diseases)) / len(expected_diseases) if expected_diseases else 0
            
            print(f"  Old system accuracy: {old_accuracy:.2%}")
            print(f"  New system accuracy: {new_accuracy:.2%}")
            
            if new_accuracy > old_accuracy:
                print("  ✅ IMPROVED SYSTEM BETTER")
            elif new_accuracy == old_accuracy:
                print("  ⚖️  SAME ACCURACY")
            else:
                print("  ❌ OLD SYSTEM BETTER")
                
        except Exception as e:
            print(f"❌ Error in test case {i}: {e}")
        
        print("=" * 60)

async def test_keyword_matching():
    """Test keyword matching functionality"""
    
    print("\n" + "=" * 80)
    print("TESTING KEYWORD MATCHING")
    print("=" * 80)
    
    from simple_disease_checker_improved import find_matching_diseases, get_disease_variants
    
    test_diseases = [
        "viêm họng cấp tính",
        "viêm tai giữa",
        "viêm mũi dị ứng", 
        "viêm dạ dày",
        "hen suyễn",
        "viêm phổi",
        "viêm gan",  # Should not match any in our limited set
        "đau đầu"    # Should not match any in our limited set
    ]
    
    for disease in test_diseases:
        print(f"\n🔍 Testing: '{disease}'")
        matching = find_matching_diseases(disease)
        variants = get_disease_variants(disease)
        
        print(f"  Matching diseases: {matching}")
        print(f"  Variants count: {len(variants)}")
        print(f"  Sample variants: {variants[:3]}...")

async def main():
    """Main test function"""
    print("🚀 Starting Disease Checker Comparison Tests")
    
    await test_keyword_matching()
    await test_disease_matching()
    
    print("\n" + "=" * 80)
    print("✅ ALL TESTS COMPLETED")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
