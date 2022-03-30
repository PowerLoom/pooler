from math import floor

def v2_pair_data_unpack(prop):
    prop = prop.replace("US$", "")
    prop = prop.replace(",", "")
    return int(prop)

def number_to_abbreviated_string(num):
    magnitudeDict={0:'', 1:'K', 2:'m', 3:'b', 4:'T', 5:'quad', 6:'quin', 7:'sext', 8:'sept', 9:'o', 10:'n', 11:'d'}
    num=floor(num)
    magnitude=0
    while num>=1000.0:
        magnitude+=1
        num=num/1000.0
    return(f'{floor(num*100.0)/100.0}{magnitudeDict[magnitude]}')
        