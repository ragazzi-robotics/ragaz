# Guidelines

## KISS principle

Ragaz adopts the KISS principle (Keep the Stuff Simple, Stupid!), so we prioritize a code simpler with reasonable 
speed than a complex one with little gain of performance. +10% speed doesn't justify +50% complexity. Yes, there are
situations where a code more complex fits better than a simpler to make the same thing but in an (very) efficient 
way. In these cases, we ask you to provide good commentaries explaining your code (if possible with tiny examples 
along the code).  

## Naming convention

Please, don't abuse on abbreviations. A good name for variable should be clear and intuitive. Obviously, there are 
cases that abbreviations are allowed, specially those well known by the most developers as *arg* (argument), 
*src* (source), etc., but as general rule, avoid stuff like this:

    at = get_type(src)

Instead, prefer use this:

    arg_type = get_type(src)

## Always try pull Ragaz code

If possible, try use Ragaz code to perform an algorithm that it handles well. You can pull C/C++ or LLVM code, but 
only when Ragaz is not able (yet) to run the code. Otherwise, convert the code to Ragaz.
